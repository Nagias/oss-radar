"""Nghiệp vụ của tính năng Quét: bắt đầu, chạy (chia lát), dừng, tiếp tục; độ phủ trung thực.

View và lệnh dòng lệnh chỉ gọi các hàm ở đây; không chứa logic riêng.
"""

import logging
import time
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Case, F, Max, Q, QuerySet, Value, When
from django.utils import timezone

from core import background
from features.catalog.models import Repository
from features.catalog.services import upsert_repositories

# Tính năng khác đọc cửa sổ nhịp sống qua services (mypy strict chỉ cho dùng tên được xuất rõ).
from features.discovery.models import LIVE_HEARTBEAT_WINDOW as LIVE_HEARTBEAT_WINDOW
from features.discovery.models import ScanResult, ScanRun, ScanSlice
from features.discovery.slicing import (
    MAX_RESULTS_PER_QUERY,
    PER_PAGE,
    SliceRange,
    build_query,
    find_forbidden_qualifier,
    pages_needed,
    resolve_root_range,
    split,
)
from integrations.github.client import GitHubClient, get_github_client
from integrations.github.errors import (
    GitHubAuthError,
    GitHubError,
    GitHubQueryError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubUnavailableError,
)
from integrations.github.pacing import CallBudget, CallBudgetExhaustedError
from integrations.github.schemas import RepoSearchPage

logger = logging.getLogger(__name__)

HEARTBEAT_CHUNK_SECONDS = 10.0  # ngủ từng khúc ≤ 10 giây, sau mỗi khúc ghi nhịp sống
SHOW_WAIT_AFTER_SECONDS = 5.0  # chờ lâu hơn thì hiện "Đang chờ GitHub tới …" trên trang
MAX_CONSECUTIVE_FAILED_SLICES = 3
# Tự chạy tiếp lần quét bị gián đoạn: chỉ trong 24 giờ và tối đa 3 lần — chính lần quét làm sập app
# thì không lặp mãi.
MAX_AUTO_RESUMES = 3
AUTO_RESUME_WINDOW = timedelta(hours=24)

# Mức quét dùng chung cho form của trang web, lệnh dòng lệnh và tính năng khác.
# Ước lượng tối đa theo khoảng cách 2,1 giây/lượt (có token) và 6,1 giây/lượt (không token).
BUDGET_CHOICES = [
    (1, "Nhanh — 1 lượt gọi (100 repo nhiều star nhất)"),
    (50, "Vừa — 50 lượt (≤ 2 phút có token, ≤ 5 phút không token)"),
    (300, "Sâu — 300 lượt (≤ 11 phút có token, ≤ 31 phút không token)"),
    (1000, "Hết cỡ — 1.000 lượt (≤ 35 phút có token, ≤ 1 giờ 42 phút không token)"),
]
_QUALIFIER_HINTS = {
    "stars:": "Không tự ghi `stars:` trong truy vấn — dùng ô Star tối thiểu / Star tối đa.",
    "created:": "Không tự ghi `created:` trong truy vấn — dùng ô Tạo từ ngày / đến ngày.",
    "sort:": "Không tự ghi `sort:` trong truy vấn — app luôn sắp theo star.",
}

REASON_BUDGET = "Hết ngân sách lượt gọi — bấm Tiếp tục để quét nốt phần còn lại."
REASON_STOPPED = "Bạn đã bấm Dừng — bấm Tiếp tục để quét tiếp."
REASON_INTERRUPTED = "Bị gián đoạn (app tắt hoặc khởi động lại giữa chừng) — bấm Tiếp tục."
REASON_CTRL_C = "Lệnh quét bị ngắt (Ctrl+C) — bấm Tiếp tục để quét tiếp."
REASON_BUSY = "App đang bận việc nền khác — bấm Tiếp tục khi app rảnh."
REASON_WAIT_TOO_LONG = "GitHub báo hết lượt gọi và bắt chờ quá lâu — bấm Tiếp tục sau ít phút."
REASON_CONNECTION = (
    "Mất kết nối GitHub liên tục ({count} lát lỗi liền nhau) — kiểm tra mạng rồi bấm Tiếp tục."
)
_UNEXPECTED_REASON = "Lỗi không mong đợi trong lúc quét — xem log của máy chủ."

# Lời giải thích cho người dùng theo từng loại lỗi GitHub; chi tiết kỹ thuật được nối thêm phía sau.
_FAILURE_REASONS: tuple[tuple[type[GitHubError], str], ...] = (
    (
        GitHubRateLimitError,
        "GitHub báo đã hết lượt gọi API. Chờ một lúc rồi quét lại "
        "(điền GITHUB_TOKEN vào .env để có nhiều lượt hơn).",
    ),
    (GitHubAuthError, "GitHub từ chối token. Kiểm tra lại GITHUB_TOKEN trong .env."),
    (GitHubQueryError, "GitHub không chấp nhận truy vấn này. Kiểm tra lại cú pháp tìm kiếm."),
    (GitHubUnavailableError, "Không gọi được GitHub hoặc GitHub đang lỗi. Thử lại sau."),
)
_UNKNOWN_GITHUB_REASON = "GitHub trả về dữ liệu không đọc được."
_PROBLEM_STATUSES = (
    ScanSlice.Status.TRUNCATED,
    ScanSlice.Status.INCOMPLETE,
    ScanSlice.Status.FAILED,
)


@dataclass(frozen=True, slots=True)
class ScanRequest:
    query: str
    min_stars: int
    max_stars: int | None
    created_from: date | None
    created_to: date | None
    budget: int
    origin: str = ScanRun.Origin.MANUAL


class ScanAlreadyRunningError(Exception):
    """Đang có lần quét khác chạy thật — mỗi lúc chỉ một lần quét."""

    def __init__(self, scan: ScanRun) -> None:
        super().__init__(f"Đang chạy lần quét #{scan.pk}")
        self.scan = scan


class StopRequestedError(Exception):
    """Người dùng đã bấm Dừng."""


class ScanSupersededError(Exception):
    """Luồng này không còn giữ lần quét (bị coi là gián đoạn, hoặc đã có lượt Tiếp tục khác)."""


# --- Bắt đầu, dừng, tiếp tục -----------------------------------------------------------------


def start_scan(request: ScanRequest) -> ScanRun:
    """Tạo lần quét mới (đã giữ chỗ "đang chạy") cùng lát gốc. Chạy thật bằng `execute_scan`."""
    with transaction.atomic():
        pause_stale_scans()
        live = live_scan()
        if live is not None:
            raise ScanAlreadyRunningError(live)
        now = timezone.now()
        scan = ScanRun.objects.create(
            query=request.query,
            min_stars=request.min_stars,
            max_stars=request.max_stars,
            created_from=request.created_from,
            created_to=request.created_to,
            budget=request.budget,
            origin=request.origin,
            status=ScanRun.Status.RUNNING,
            started_at=now,
            heartbeat_at=now,
        )
        root = resolve_root_range(
            created_from=request.created_from,
            created_to=request.created_to,
            min_stars=request.min_stars,
            max_stars=request.max_stars,
            today=timezone.localdate(),
        )
        ScanSlice.objects.create(
            scan_run=scan,
            stack_order=1,
            created_from=root.created_from,
            created_to=root.created_to,
            stars_min=root.stars_min,
            stars_max=root.stars_max,
        )
    return scan


def resume_scan(scan: ScanRun, *, extra_budget: int) -> ScanRun:
    """Cho lần quét tạm dừng/còn sót chạy tiếp: làm lại lát lỗi, chưa chắc đủ; thêm ngân sách."""
    with transaction.atomic():
        pause_stale_scans()
        scan.refresh_from_db()
        if not scan.can_resume:
            raise ValueError(f"Lần quét #{scan.pk} không ở trạng thái tiếp tục được.")
        live = live_scan()
        if live is not None:
            raise ScanAlreadyRunningError(live)
        scan.slices.filter(
            status__in=[ScanSlice.Status.FAILED, ScanSlice.Status.INCOMPLETE]
        ).update(status=ScanSlice.Status.PENDING, retried_incomplete=False, error_message="")
        scan.budget += extra_budget
        scan.status = ScanRun.Status.RUNNING
        scan.heartbeat_at = timezone.now()
        scan.finished_at = None
        scan.waiting_until = None
        scan.stop_requested = False
        scan.stop_reason = ""
        scan.runner_token = ""  # nhả mã: luồng cũ (nếu còn sống) thấy mất quyền và tự rút lui
        scan.save()
    return scan


def request_stop(scan: ScanRun) -> None:
    """Bấm Dừng: luồng quét dừng trước lượt gọi kế tiếp (hoặc ngay khi đang chờ)."""
    ScanRun.objects.filter(pk=scan.pk).update(stop_requested=True)


def live_scan() -> ScanRun | None:
    """Lần quét đang chạy thật (nhịp sống còn mới), ở bất kỳ tiến trình nào."""
    threshold = timezone.now() - LIVE_HEARTBEAT_WINDOW
    return (
        ScanRun.objects.filter(status=ScanRun.Status.RUNNING, heartbeat_at__gte=threshold)
        .order_by("-heartbeat_at")
        .first()
    )


def pause_stale_scans() -> int:
    """Lần quét "đang chạy" mà nhịp sống đã cũ → bị gián đoạn → chuyển sang Tạm dừng.

    Người dùng đã bấm Dừng nhưng app tắt trước khi luồng quét kịp thấy → ghi là "đã bấm Dừng",
    không phải "bị gián đoạn", để không bị tự chạy tiếp tốn lượt gọi người dùng đã từ chối.
    Giữ nguyên `heartbeat_at`: nó là lúc bị gián đoạn, `resume_interrupted_scan` dựa vào đó.
    """
    threshold = timezone.now() - LIVE_HEARTBEAT_WINDOW
    reason = Case(
        When(stop_requested=True, then=Value(REASON_STOPPED)),
        default=Value(REASON_INTERRUPTED),
    )
    return (
        ScanRun.objects.filter(status=ScanRun.Status.RUNNING)
        .filter(Q(heartbeat_at__lt=threshold) | Q(heartbeat_at__isnull=True))
        .update(status=ScanRun.Status.PAUSED, stop_reason=reason, waiting_until=None)
    )


def resume_interrupted_scan(*, now: datetime | None = None) -> ScanRun | None:
    """Việc định kỳ: tự chạy tiếp lần quét tay bị gián đoạn gần nhất, chạy tại chỗ tới khi dừng.

    Chỉ lần quét bị gián đoạn (không phải bấm Dừng, Ctrl+C hay hết ngân sách), trong 24 giờ, tối
    đa 3 lần. Lần quét hằng ngày do chính lượt hằng ngày nối lại. Có lần quét đang chạy thì chờ
    nhịp sau. Trả lần quét đã chạy tiếp, hoặc `None` nếu không có gì để làm.
    """
    pause_stale_scans()
    if live_scan() is not None:
        return None
    moment = now if now is not None else timezone.now()
    scan = ScanRun.objects.filter(
        status=ScanRun.Status.PAUSED,
        stop_reason=REASON_INTERRUPTED,
        stop_requested=False,
        origin=ScanRun.Origin.MANUAL,
        auto_resume_count__lt=MAX_AUTO_RESUMES,
        heartbeat_at__gte=moment - AUTO_RESUME_WINDOW,
    ).first()
    if scan is None:
        return None
    try:
        # Đếm cùng transaction với lúc nối lại, TRƯỚC khi chạy: lần quét làm sập app vẫn bị đếm.
        with transaction.atomic():
            resume_scan(scan, extra_budget=0)
            ScanRun.objects.filter(pk=scan.pk).update(
                auto_resume_count=F("auto_resume_count") + 1, last_auto_resume_at=moment
            )
    except ScanAlreadyRunningError as exc:
        # Tiến trình khác (vd lệnh `scan`) vừa bắt đầu quét sau lần kiểm ở trên: chờ nhịp sau.
        logger.info("Chưa tự chạy tiếp lần quét #%s: %s", scan.pk, exc)
        return None
    logger.info("Tự chạy tiếp lần quét #%s bị gián đoạn", scan.pk)
    background.relabel(f"Lần quét #{scan.pk} (tự chạy tiếp)")
    execute_scan(scan.pk)
    scan.refresh_from_db()
    return scan


def release_unstarted_scan(scan: ScanRun, *, refund_budget: int = 0) -> None:
    """Lần quét vừa giữ chỗ nhưng luồng nền đã bị việc khác chiếm → Tạm dừng, chờ bấm Tiếp tục.

    Không để nó "đang chạy" nằm chờ sau một việc dài (vd lượt hằng ngày): nhịp sống sẽ cũ đi và nó
    bị coi là gián đoạn. Lý do dừng khác "bị gián đoạn" nên cũng không bị tự chạy tiếp.
    `refund_budget`: phần ngân sách lượt Tiếp tục vừa thêm — chưa chạy được thì trả lại, để lần bấm
    Tiếp tục sau không phải thêm một mức nữa.
    """
    ScanRun.objects.filter(pk=scan.pk, status=ScanRun.Status.RUNNING).update(
        status=ScanRun.Status.PAUSED,
        stop_reason=REASON_BUSY,
        budget=F("budget") - refund_budget,
        heartbeat_at=None,
        runner_token="",
        waiting_until=None,
    )
    scan.refresh_from_db()


# --- Đọc dữ liệu cho trang web và lệnh -------------------------------------------------------


def recent_scans(limit: int = 10) -> QuerySet[ScanRun]:
    """Các lần quét tay mới nhất trước (lần quét hằng ngày xem ở báo cáo hằng ngày)."""
    return ScanRun.objects.filter(origin=ScanRun.Origin.MANUAL)[:limit]


def repositories_seen_in(scan_ids: Collection[int]) -> QuerySet[Repository]:
    """Các repo (không lặp) có mặt trong kết quả của các lần quét này."""
    return Repository.objects.filter(scan_results__scan_run_id__in=list(scan_ids)).distinct()


def prune_daily_results(*, before: datetime) -> int:
    """Xoá danh sách repo của lần quét hằng ngày tạo trước `before`; trả số dòng đã xoá.

    Phần tóm tắt của lần quét giữ nguyên; chỉ lần quét thật sự bị xoá dòng mới được đánh dấu "đã
    dọn" (lần quét không có repo nào thì không có gì để dọn). Lần quét tay không bị dọn.
    """
    old_daily = ScanRun.objects.filter(origin=ScanRun.Origin.DAILY, created_at__lt=before)
    old_results = ScanResult.objects.filter(scan_run__in=old_daily)
    with transaction.atomic():
        # Đánh dấu trước khi xoá: sau khi xoá thì không còn biết lần quét nào từng có dòng.
        ScanRun.objects.filter(pk__in=old_results.values("scan_run_id")).update(results_pruned=True)
        deleted, _ = old_results.delete()
    return deleted


def forbidden_qualifier_hint(query: str) -> str | None:
    """Lời nhắc khi truy vấn tự ghi điều kiện app tự thêm (`stars:`, `created:`, `sort:`)."""
    forbidden = find_forbidden_qualifier(query)
    return None if forbidden is None else _QUALIFIER_HINTS[forbidden]


def scan_results(scan: ScanRun) -> QuerySet[ScanResult]:
    """Kết quả của một lần quét, sắp theo star giảm dần."""
    return scan.results.select_related("repository").order_by(
        "-repository__stars", "repository__full_name"
    )


@dataclass(frozen=True, slots=True)
class SliceProgress:
    finished: int
    total: int


def slice_progress(scan: ScanRun) -> SliceProgress:
    """Số lát đã xử lý / tổng số lát (chỉ tính lát lá — lát đã chia nhỏ không tính)."""
    leaves = scan.slices.exclude(status=ScanSlice.Status.SPLIT)
    pending = leaves.filter(status=ScanSlice.Status.PENDING).count()
    total = leaves.count()
    return SliceProgress(finished=total - pending, total=total)


def problem_slices(scan: ScanRun) -> QuerySet[ScanSlice]:
    """Các lát bị cắt, chưa chắc đủ hoặc lỗi — để người dùng biết còn sót ở đâu."""
    return scan.slices.filter(status__in=_PROBLEM_STATUSES).order_by("created_from", "stars_min")


# --- Chạy lần quét ---------------------------------------------------------------------------


class HeartbeatSleeper:
    """Hàm ngủ cho client GitHub: ngủ từng khúc, ghi nhịp sống sau mỗi khúc, thấy Dừng thì dừng.

    `token` là mã chủ quyền của lượt chạy: mất mã (lần quét bị coi là gián đoạn, hoặc đã có lượt
    Tiếp tục khác) thì dừng ngay và không ghi gì nữa.
    """

    def __init__(
        self, scan_id: int, *, token: str = "", chunk: float = HEARTBEAT_CHUNK_SECONDS
    ) -> None:
        self._scan_id = scan_id
        self._token = token
        self._chunk = chunk

    def __call__(self, seconds: float) -> None:
        show_wait = seconds > SHOW_WAIT_AFTER_SECONDS
        if show_wait:
            self._owned().update(waiting_until=timezone.now() + timedelta(seconds=seconds))
        try:
            remaining = seconds
            while remaining > 0:
                step = min(self._chunk, remaining)
                time.sleep(step)
                remaining -= step
                self.beat()
        finally:
            if show_wait:
                self._owned().update(waiting_until=None)

    def beat(self) -> None:
        row = (
            ScanRun.objects.filter(pk=self._scan_id)
            .values("status", "runner_token", "stop_requested")
            .first()
        )
        if row is None or row["status"] != ScanRun.Status.RUNNING:
            raise ScanSupersededError
        if row["runner_token"] != self._token:
            raise ScanSupersededError
        if row["stop_requested"]:
            raise StopRequestedError
        self._owned().update(heartbeat_at=timezone.now())

    def _owned(self) -> QuerySet[ScanRun]:
        return ScanRun.objects.filter(pk=self._scan_id, runner_token=self._token)


def execute_scan(scan_id: int) -> None:
    """Chạy lần quét tới khi xong, hết ngân sách, bị dừng hoặc lỗi. Gọi từ luồng nền hoặc lệnh."""
    token = uuid.uuid4().hex
    claimed = ScanRun.objects.filter(
        pk=scan_id, status=ScanRun.Status.RUNNING, runner_token=""
    ).update(runner_token=token, heartbeat_at=timezone.now())
    if not claimed:
        logger.info(
            "Bỏ qua lần quét #%s: không ở trạng thái chạy hoặc đã có lượt khác giữ", scan_id
        )
        return
    scan = ScanRun.objects.get(pk=scan_id)
    sleeper = HeartbeatSleeper(scan.pk, token=token)
    budget = CallBudget(max(0, scan.budget - scan.api_calls_used))
    runner = _ScanRunner(
        scan, budget, token=token, calls_before=scan.api_calls_used, sleeper=sleeper
    )
    try:
        with get_github_client(sleep=sleeper, budget=budget) as github:
            runner.run(github)
    except ScanSupersededError:
        logger.info("Lần quét #%s: lượt chạy cũ rút lui, không ghi gì thêm", scan.pk)
    except KeyboardInterrupt:
        runner.finish(ScanRun.Status.PAUSED, reason=REASON_CTRL_C)
        raise
    except Exception:
        logger.exception("Lần quét #%s gặp lỗi không mong đợi", scan.pk)
        runner.finish(
            ScanRun.Status.FAILED,
            error=_UNEXPECTED_REASON,
            error_kind=ScanRun.ErrorKind.UNEXPECTED,
        )
        raise


class _ScanRunner:
    def __init__(
        self,
        scan: ScanRun,
        budget: CallBudget,
        *,
        token: str,
        calls_before: int,
        sleeper: HeartbeatSleeper,
    ) -> None:
        self.scan = scan
        self.budget = budget
        self.token = token
        self.calls_before = calls_before
        self.sleeper = sleeper

    def run(self, github: GitHubClient) -> None:
        failed_in_a_row = 0
        try:
            while True:
                self.sleeper.beat()  # ghi nhịp sống + dừng nếu người dùng bấm Dừng
                slice_ = self.scan.slices.filter(status=ScanSlice.Status.PENDING).first()
                if slice_ is None:
                    self._finish_all_slices()
                    return
                try:
                    self._process(github, slice_)
                    failed_in_a_row = 0
                except (GitHubUnavailableError, GitHubResponseError) as exc:
                    self._fail_slice(slice_, exc)
                    failed_in_a_row += 1
                    if failed_in_a_row >= MAX_CONSECUTIVE_FAILED_SLICES:
                        reason = REASON_CONNECTION.format(count=failed_in_a_row)
                        self.finish(ScanRun.Status.PAUSED, reason=reason)
                        return
        except CallBudgetExhaustedError:
            self.finish(ScanRun.Status.SUCCEEDED_PARTIAL, reason=REASON_BUDGET)
        except StopRequestedError:
            self.finish(ScanRun.Status.PAUSED, reason=REASON_STOPPED)
        except GitHubRateLimitError as exc:
            logger.warning("Lần quét #%s phải tạm dừng vì hết lượt: %r", self.scan.pk, exc)
            self.finish(ScanRun.Status.PAUSED, reason=REASON_WAIT_TOO_LONG)
        except (GitHubAuthError, GitHubQueryError) as exc:
            logger.warning("Lần quét #%s lỗi từ GitHub: %r", self.scan.pk, exc)
            kind = (
                ScanRun.ErrorKind.AUTH
                if isinstance(exc, GitHubAuthError)
                else ScanRun.ErrorKind.QUERY
            )
            self.finish(
                ScanRun.Status.FAILED,
                error=f"{_reason_for(exc)} (Chi tiết: {exc})",
                error_kind=kind,
            )

    def _process(self, github: GitHubClient, slice_: ScanSlice) -> None:
        query = build_query(self.scan.query, slice_.range)
        slice_.pages_fetched = 0
        slice_.fetched_count = 0
        first = self._fetch(github, slice_, query, page=1)
        slice_.total_count = first.total_count
        if slice_.stack_order == 1:
            self.scan.total_count = first.total_count
            self._update(total_count=first.total_count)

        if first.total_count > MAX_RESULTS_PER_QUERY:
            top_stars = first.items[0].stars if first.items else slice_.stars_min
            halves = split(slice_.range, top_stars=top_stars)
            if halves is not None:
                self._replace_with_children(slice_, *halves)
                self._log_slice(slice_, "quá 1.000 → chia đôi")
                return

        complete = self._fetch_remaining_pages(github, slice_, query, first)
        if first.total_count > MAX_RESULTS_PER_QUERY:
            missing = first.total_count - MAX_RESULTS_PER_QUERY
            slice_.status = ScanSlice.Status.TRUNCATED
            slice_.error_message = (
                f"GitHub có {first.total_count} kết quả cùng ngày, cùng mức star nhưng chỉ cho lấy "
                f"1.000 — thiếu {missing}."
            )
        elif complete:
            slice_.status = ScanSlice.Status.DONE
        elif not slice_.retried_incomplete:
            slice_.retried_incomplete = True  # vẫn `pending` → được làm lại ngay ở vòng sau
        else:
            slice_.status = ScanSlice.Status.INCOMPLETE
            slice_.error_message = "GitHub trả thiếu so với số nó báo, kể cả khi làm lại."
        slice_.save()
        retrying = slice_.status == ScanSlice.Status.PENDING
        self._log_slice(slice_, "chưa đủ → làm lại" if retrying else slice_.get_status_display())

    def _log_slice(self, slice_: ScanSlice, outcome: str) -> None:
        """Một dòng tiến độ cho mỗi lát — hiện ở màn hình lệnh `scan` và log của server."""
        stars_to = "∞" if slice_.stars_max is None else slice_.stars_max
        logger.info(
            "Lần quét #%s: lát %s..%s, star %s..%s — %s (GitHub báo %s, lấy %s); "
            "tổng đã lấy %s, lượt gọi %s/%s",
            self.scan.pk,
            slice_.created_from,
            slice_.created_to,
            slice_.stars_min,
            stars_to,
            outcome,
            slice_.total_count,
            slice_.fetched_count,
            self.scan.fetched_count,
            self.calls_before + self.budget.used,
            self.scan.budget,
        )

    def _fetch_remaining_pages(
        self, github: GitHubClient, slice_: ScanSlice, query: str, first: RepoSearchPage
    ) -> bool:
        """Lấy trang 2.. của lát. Trả False nếu GitHub báo chưa đủ hoặc trả hụt trang."""
        expected = min(first.total_count, MAX_RESULTS_PER_QUERY)
        complete = not first.incomplete_results
        last = first
        for page in range(2, pages_needed(first.total_count) + 1):
            if len(last.items) < PER_PAGE:
                break
            last = self._fetch(github, slice_, query, page=page)
            complete = complete and not last.incomplete_results
        return complete and slice_.fetched_count >= expected

    def _fetch(
        self, github: GitHubClient, slice_: ScanSlice, query: str, *, page: int
    ) -> RepoSearchPage:
        try:
            result = github.search_repositories(query, per_page=PER_PAGE, page=page)
        finally:
            self._save_calls()
        with transaction.atomic():
            outcomes = upsert_repositories(result.items, seen_at=timezone.now())
            ScanResult.objects.bulk_create(
                [
                    ScanResult(scan_run=self.scan, repository=o.repository, is_new=o.created)
                    for o in outcomes
                ],
                ignore_conflicts=True,
            )
        slice_.pages_fetched += 1
        slice_.fetched_count += len(result.items)
        self._save_counts()
        return result

    def _replace_with_children(
        self, slice_: ScanSlice, first: SliceRange, later: SliceRange
    ) -> None:
        """Lát quá 1.000 kết quả → 2 lát con. `first` nhận thứ tự lớn hơn nên được làm trước."""
        next_order = (self.scan.slices.aggregate(top=Max("stack_order"))["top"] or 0) + 1
        with transaction.atomic():
            for offset, rng in enumerate((later, first)):
                ScanSlice.objects.create(
                    scan_run=self.scan,
                    stack_order=next_order + offset,
                    created_from=rng.created_from,
                    created_to=rng.created_to,
                    stars_min=rng.stars_min,
                    stars_max=rng.stars_max,
                )
            slice_.status = ScanSlice.Status.SPLIT
            slice_.save()

    def _fail_slice(self, slice_: ScanSlice, exc: GitHubError) -> None:
        logger.warning("Lát %s lỗi: %r", slice_, exc)
        slice_.status = ScanSlice.Status.FAILED
        slice_.error_message = f"{_reason_for(exc)} (Chi tiết: {exc})"
        slice_.save()

    def _finish_all_slices(self) -> None:
        problems = problem_slices(self.scan)
        if not problems.exists():
            self.finish(ScanRun.Status.SUCCEEDED)
            return
        counts = {status: problems.filter(status=status).count() for status in _PROBLEM_STATUSES}
        reason = (
            f"Còn {problems.count()} lát chưa đủ: {counts[ScanSlice.Status.TRUNCATED]} bị cắt, "
            f"{counts[ScanSlice.Status.INCOMPLETE]} chưa chắc đủ, "
            f"{counts[ScanSlice.Status.FAILED]} lỗi — xem danh sách bên dưới."
        )
        self.finish(ScanRun.Status.SUCCEEDED_PARTIAL, reason=reason)

    def finish(
        self,
        status: ScanRun.Status,
        *,
        reason: str = "",
        error: str = "",
        error_kind: str = "",
    ) -> None:
        self._save_calls()
        self._update(
            status=status,
            stop_reason=reason,
            error_message=error,
            error_kind=error_kind,
            finished_at=timezone.now(),
            waiting_until=None,
            stop_requested=False,
            runner_token="",
        )

    def _save_calls(self) -> None:
        self._update(
            api_calls_used=self.calls_before + self.budget.used, heartbeat_at=timezone.now()
        )

    def _save_counts(self) -> None:
        results = self.scan.results
        self.scan.fetched_count = results.count()
        created = results.filter(is_new=True).count()
        self._update(
            fetched_count=self.scan.fetched_count,
            created_count=created,
            updated_count=self.scan.fetched_count - created,
        )

    def _update(self, **fields: object) -> None:
        """Mọi lần ghi lần quét đều kèm điều kiện "còn giữ mã" — luồng cũ không ghi đè được."""
        ScanRun.objects.filter(pk=self.scan.pk, runner_token=self.token).update(**fields)


def _reason_for(exc: GitHubError) -> str:
    for error_type, reason in _FAILURE_REASONS:
        if isinstance(exc, error_type):
            return reason
    return _UNKNOWN_GITHUB_REASON
