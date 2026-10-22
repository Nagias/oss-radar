"""Nghiệp vụ của tính năng Quét: bắt đầu, chạy (chia lát), dừng, tiếp tục; độ phủ trung thực.

View và lệnh dòng lệnh chỉ gọi các hàm ở đây; không chứa logic riêng.
"""

import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Max, Q, QuerySet
from django.utils import timezone

from features.catalog.services import upsert_repositories
from features.discovery.models import LIVE_HEARTBEAT_WINDOW, ScanResult, ScanRun, ScanSlice
from features.discovery.slicing import (
    MAX_RESULTS_PER_QUERY,
    PER_PAGE,
    SliceRange,
    build_query,
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

REASON_BUDGET = "Hết ngân sách lượt gọi — bấm Tiếp tục để quét nốt phần còn lại."
REASON_STOPPED = "Bạn đã bấm Dừng — bấm Tiếp tục để quét tiếp."
REASON_INTERRUPTED = "Bị gián đoạn (app tắt hoặc khởi động lại giữa chừng) — bấm Tiếp tục."
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


class ScanAlreadyRunningError(Exception):
    """Đang có lần quét khác chạy thật — mỗi lúc chỉ một lần quét."""

    def __init__(self, scan: ScanRun) -> None:
        super().__init__(f"Đang chạy lần quét #{scan.pk}")
        self.scan = scan


class StopRequestedError(Exception):
    """Người dùng đã bấm Dừng."""


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
    """Lần quét "đang chạy" mà nhịp sống đã cũ → bị gián đoạn → chuyển sang Tạm dừng."""
    # DEBT(D-006): chỉ chuyển sang Tạm dừng; chưa tự chạy tiếp khi mở lại app (làm ở F-005).
    threshold = timezone.now() - LIVE_HEARTBEAT_WINDOW
    return (
        ScanRun.objects.filter(status=ScanRun.Status.RUNNING)
        .filter(Q(heartbeat_at__lt=threshold) | Q(heartbeat_at__isnull=True))
        .update(status=ScanRun.Status.PAUSED, stop_reason=REASON_INTERRUPTED, waiting_until=None)
    )


# --- Đọc dữ liệu cho trang web và lệnh -------------------------------------------------------


def recent_scans(limit: int = 10) -> QuerySet[ScanRun]:
    """Các lần quét mới nhất trước."""
    return ScanRun.objects.all()[:limit]


def scan_results(scan: ScanRun) -> QuerySet[ScanResult]:
    """Kết quả của một lần quét, sắp theo star giảm dần."""
    return scan.results.select_related("repository").order_by(
        "-repository__stars", "repository__full_name"
    )


def problem_slices(scan: ScanRun) -> QuerySet[ScanSlice]:
    """Các lát bị cắt, chưa chắc đủ hoặc lỗi — để người dùng biết còn sót ở đâu."""
    return scan.slices.filter(status__in=_PROBLEM_STATUSES).order_by("created_from", "stars_min")


# --- Chạy lần quét ---------------------------------------------------------------------------


class HeartbeatSleeper:
    """Hàm ngủ cho client GitHub: ngủ từng khúc, ghi nhịp sống sau mỗi khúc, thấy Dừng thì dừng."""

    def __init__(self, scan_id: int, *, chunk: float = HEARTBEAT_CHUNK_SECONDS) -> None:
        self._scan_id = scan_id
        self._chunk = chunk

    def __call__(self, seconds: float) -> None:
        show_wait = seconds > SHOW_WAIT_AFTER_SECONDS
        if show_wait:
            until = timezone.now() + timedelta(seconds=seconds)
            ScanRun.objects.filter(pk=self._scan_id).update(waiting_until=until)
        try:
            remaining = seconds
            while remaining > 0:
                step = min(self._chunk, remaining)
                time.sleep(step)
                remaining -= step
                self.beat()
        finally:
            if show_wait:
                ScanRun.objects.filter(pk=self._scan_id).update(waiting_until=None)

    def beat(self) -> None:
        ScanRun.objects.filter(pk=self._scan_id).update(heartbeat_at=timezone.now())
        if ScanRun.objects.filter(pk=self._scan_id, stop_requested=True).exists():
            raise StopRequestedError


def execute_scan(scan_id: int) -> None:
    """Chạy lần quét tới khi xong, hết ngân sách, bị dừng hoặc lỗi. Gọi từ luồng nền hoặc lệnh."""
    scan = ScanRun.objects.get(pk=scan_id)
    if scan.status != ScanRun.Status.RUNNING:
        logger.info("Bỏ qua lần quét #%s vì đang ở trạng thái %s", scan.pk, scan.status)
        return
    sleeper = HeartbeatSleeper(scan.pk)
    budget = CallBudget(max(0, scan.budget - scan.api_calls_used))
    runner = _ScanRunner(scan, budget, calls_before=scan.api_calls_used, sleeper=sleeper)
    try:
        with get_github_client(sleep=sleeper, budget=budget) as github:
            runner.run(github)
    except Exception:
        logger.exception("Lần quét #%s gặp lỗi không mong đợi", scan.pk)
        runner.finish(ScanRun.Status.FAILED, error=_UNEXPECTED_REASON)
        raise


class _ScanRunner:
    def __init__(
        self, scan: ScanRun, budget: CallBudget, *, calls_before: int, sleeper: HeartbeatSleeper
    ) -> None:
        self.scan = scan
        self.budget = budget
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
            self.finish(ScanRun.Status.FAILED, error=f"{_reason_for(exc)} (Chi tiết: {exc})")

    def _process(self, github: GitHubClient, slice_: ScanSlice) -> None:
        query = build_query(self.scan.query, slice_.range)
        slice_.pages_fetched = 0
        slice_.fetched_count = 0
        first = self._fetch(github, slice_, query, page=1)
        slice_.total_count = first.total_count
        if slice_.stack_order == 1:
            self.scan.total_count = first.total_count
            self.scan.save(update_fields=["total_count"])

        if first.total_count > MAX_RESULTS_PER_QUERY:
            top_stars = first.items[0].stars if first.items else slice_.stars_min
            halves = split(slice_.range, top_stars=top_stars)
            if halves is not None:
                self._replace_with_children(slice_, *halves)
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

    def finish(self, status: ScanRun.Status, *, reason: str = "", error: str = "") -> None:
        self._save_calls()
        self.scan.status = status
        self.scan.stop_reason = reason
        self.scan.error_message = error
        self.scan.finished_at = timezone.now()
        self.scan.waiting_until = None
        self.scan.stop_requested = False
        self.scan.save()

    def _save_calls(self) -> None:
        self.scan.api_calls_used = self.calls_before + self.budget.used
        self.scan.heartbeat_at = timezone.now()
        self.scan.save(update_fields=["api_calls_used", "heartbeat_at"])

    def _save_counts(self) -> None:
        results = self.scan.results
        self.scan.fetched_count = results.count()
        self.scan.created_count = results.filter(is_new=True).count()
        self.scan.updated_count = self.scan.fetched_count - self.scan.created_count
        self.scan.save(update_fields=["fetched_count", "created_count", "updated_count"])


def _reason_for(exc: GitHubError) -> str:
    for error_type, reason in _FAILURE_REASONS:
        if isinstance(exc, error_type):
            return reason
    return _UNKNOWN_GITHUB_REASON
