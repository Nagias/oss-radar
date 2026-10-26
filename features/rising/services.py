"""Nghiệp vụ của Rising star: lượt quét hằng ngày theo danh sách theo dõi.

Mỗi ngày (giờ Việt Nam) có tối đa một lượt, gồm 6 bước: quét lại danh sách theo dõi → lọc thô →
xác minh → lấy hồ sơ chủ của rising star (F-006) → phân loại repo của lượt bằng AI (F-010) →
lập báo cáo. Việc định kỳ `classify_backlog_if_due` phân loại dần phần còn lại của kho. Bước đang
làm lưu trong CSDL: bị gián đoạn thì lần sau làm tiếp từ bước dở.
Lượt tự bắt đầu sau 7:00 (`run_daily_if_due`, việc định kỳ của bộ nhịp), hoặc khi bấm "Chạy ngay" /
lệnh `daily` (`prepare_daily_run` rồi `execute_daily_run`).

Phần cuối file là các hàm đọc cho trang web: báo cáo (`daily_report`, `latest_report_run`…), trạng
thái hôm nay (`today_status`), danh sách theo dõi (`watch_overview`), ước lượng lượt gọi mỗi ngày
(`daily_estimate`) và lịch sử các lượt (`recent_daily_runs`).

View và lệnh dòng lệnh chỉ gọi các hàm ở đây; không chứa logic riêng.
"""

# DEBT(D-009): file ~1.400 dòng (QĐ R11 giữ một services.py); tách ở PR fix/ ngay sau F-006.

import logging
import math
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as clock_time

from django.conf import settings
from django.db import transaction
from django.db.models import F, Max, OuterRef, QuerySet, Subquery, Sum
from django.utils import formats, timezone

from core import background
from features.catalog import services as catalog
from features.catalog.models import Repository
from features.discovery import services as discovery
from features.discovery.models import ScanRun
from features.rising import growth
from features.rising.models import DailyRun, DailyRunScan, RisingCheck, WatchQuery
from features.scoring import services as scoring
from features.scoring.services import REVIEW_FROM, GrowthFacts, Score
from features.taxonomy import services as taxonomy
from integrations.github.client import GitHubClient, get_github_client
from integrations.github.errors import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubQueryError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubUnavailableError,
)
from integrations.github.pacing import (
    MIN_INTERVAL_ANONYMOUS,
    MIN_INTERVAL_WITH_TOKEN,
    CallBudget,
    CallBudgetExhaustedError,
)
from integrations.github.schemas import StarHistory
from integrations.llm.client import get_llm_client, llm_configured
from integrations.llm.errors import LlmError

logger = logging.getLogger(__name__)

# 7:00 giờ Việt Nam = 0:00 UTC: chạy sau mốc này thì hôm qua (ngày UTC, ngày GitHub dùng cho lịch sử
# star) đã trọn.
DAILY_RUN_AFTER = clock_time(7, 0)
# Lượt bị gián đoạn hoặc bị GitHub/mạng chặn tự chạy tiếp tối đa 3 lần (đếm chung): một bước làm sập
# app thì không lặp mãi, không đốt quota.
MAX_AUTO_CONTINUES = 3
# Bị GitHub/mạng chặn thì chờ ít nhất chừng này mới tự chạy tiếp: gọi lại ngay chỉ bị chặn tiếp.
RETRY_LATER_AFTER = timedelta(minutes=15)
_RETRY_MINUTES = int(RETRY_LATER_AFTER.total_seconds() // 60)
# Xác minh: 1 lượt gọi lịch sử star cho mỗi ứng viên. Không token thì hạn mức core chỉ 60 lượt/giờ.
VERIFY_BUDGET_WITH_TOKEN = 300
VERIFY_BUDGET_ANONYMOUS = 50
# Hồ sơ chủ repo (F-006): 1 lượt gọi mỗi chủ của rising star. Không token thì hạn mức core (60 lượt
# /giờ) dùng chung với bước xác minh, nên chỉ lấy ít.
OWNER_BUDGET_WITH_TOKEN = 100
OWNER_BUDGET_ANONYMOUS = 10
# Phân loại bằng AI (F-010): trong lượt chỉ repo của lượt (rising trước) để báo cáo không ra
# muộn; phần còn lại của kho do việc định kỳ phân loại dần, mỗi nhịp tối đa 10 lượt gọi.
DAILY_RUN_CLASSIFY_CALLS = 5
BACKLOG_CALLS_PER_TICK = 10
BACKLOG_PAUSE_AFTER_ERROR = timedelta(minutes=30)
# Ảnh chụp star và danh sách repo của lần quét hằng ngày chỉ giữ chừng này ngày (thiết kế mục 8):
# ảnh chụp chỉ làm radar cho 7 tới 30 ngày, lịch sử dài hạn đã có ở GitHub.
RETENTION_DAYS = 35

EMPTY_WATCH_LIST_NOTE = "Danh sách theo dõi trống — thêm truy vấn ở trang Theo dõi."
REASON_STOPPED = "Bạn đã bấm Dừng — bấm Chạy tiếp để làm tiếp."
REASON_CTRL_C = "Lệnh bị ngắt (Ctrl+C) — bấm Chạy tiếp để làm tiếp."
REASON_INTERRUPTED = (
    "Bị gián đoạn (app tắt hoặc khởi động lại giữa chừng) — app tự chạy tiếp ở nhịp sau "
    f"(tối đa {MAX_AUTO_CONTINUES} lần), hoặc bấm Chạy tiếp."
)
REASON_BLOCKED = (
    "GitHub hoặc mạng đang chặn ở truy vấn «{query}» (lần quét #{scan_id}) — app tự chạy tiếp sau "
    "ít nhất {minutes} phút."
)
REASON_BUSY = (
    "Đang có lần quét khác chạy (#{scan_id}) — app tự chạy tiếp sau ít nhất {minutes} phút."
)
REASON_BUSY_APP = "App đang bận việc nền khác — bấm Chạy tiếp khi app rảnh."
REASON_VERIFY_BLOCKED = (
    "GitHub hoặc mạng đang chặn lúc xác minh lịch sử star — app tự chạy tiếp sau ít nhất "
    "{minutes} phút."
)
REASON_VERIFY_AUTH = (
    "Xác minh lịch sử star: GitHub từ chối token — kiểm tra lại GITHUB_TOKEN trong .env. "
    "(Chi tiết: {detail})"
)
VERIFY_BUDGET_NOTE = "Hết ngân sách xác minh — {count} ứng viên chưa xác minh."
UNREADABLE_HISTORY_NOTE = (
    "Không xác minh được {repo}: GitHub trả lịch sử star không đọc được — repo nằm ở mục chưa "
    "xác minh. (Chi tiết: {detail})"
)
OWNERS_BLOCKED_NOTE = (
    "Lấy hồ sơ chủ repo bị ngắt ({detail}) — {count} chủ repo chưa có hồ sơ, lượt sau lấy tiếp "
    "(điểm nghi star giả của repo đó chưa tính phần hồ sơ chủ)."
)
CLASSIFY_BLOCKED_NOTE = (
    "Phân loại repo bị ngắt ({detail}) — {count} repo chưa có nhãn, app phân loại dần sau."
)
_CLASSIFY_BUSY = "đang có lần phân loại khác"
_OWNERS_STOPPED = "bạn bấm Dừng"
_OWNERS_BLOCKED = "GitHub hoặc mạng đang chặn"
_OWNERS_AUTH = "GitHub từ chối token — kiểm tra lại GITHUB_TOKEN trong .env"
OWNER_BUDGET_NOTE = (
    "Hết ngân sách hồ sơ chủ repo — {count} chủ repo chưa có hồ sơ (điểm nghi star giả của repo "
    "đó chưa tính phần hồ sơ chủ)."
)
UNREADABLE_OWNER_NOTE = "Không đọc được hồ sơ chủ repo {login} — sẽ thử lại lượt sau. ({detail})"
_UNEXPECTED_REASON = "Lỗi không mong đợi trong lượt quét hằng ngày — xem log của máy chủ."
# Lý do "mất kết nối" của lần quét có điền số lát lỗi → nhận ra bằng phần đầu cố định của câu.
_CONNECTION_PREFIX = discovery.REASON_CONNECTION.partition("{")[0]
_SCAN_FINISHED = (
    ScanRun.Status.SUCCEEDED,
    ScanRun.Status.SUCCEEDED_PARTIAL,
    ScanRun.Status.FAILED,
)
_SCAN_UNFINISHED = (ScanRun.Status.RUNNING, ScanRun.Status.PAUSED)
# Lỗi tự khỏi được sau khi người dùng sửa (token, code) → chạy tiếp thì quét lại truy vấn đó bằng
# một lần quét mới. Truy vấn sai cú pháp thì không tự khỏi → coi như đã xong.
_RESCAN_ERROR_KINDS = (ScanRun.ErrorKind.AUTH, ScanRun.ErrorKind.UNEXPECTED)


class DailyRunBlockedError(Exception):
    """Không bắt đầu hay chạy tiếp được lượt hôm nay: đã xong, hoặc đang có việc khác chạy thật."""


class DailySupersededError(Exception):
    """Luồng này không còn giữ lượt (bị coi là gián đoạn, bị đóng, hoặc luồng khác đã nối lại)."""


class _DailyStopRequestedError(Exception):
    """Người dùng bấm Dừng trong lúc xác minh: thôi chờ GitHub, tạm dừng lượt."""


# --- Nhịp sống, dọn lượt cũ ------------------------------------------------------------------


def live_daily_run() -> DailyRun | None:
    """Lượt đang chạy thật: nhịp sống của chính lượt, hoặc của lần quét con, còn mới.

    Ở bước quét lại, lượt không tự ghi nhịp sống trong lúc lần quét con chạy (có khi hàng chục
    phút) — lần quét con còn sống thì lượt còn sống. Nhịp sống luôn so với giờ thật, vì nó được ghi
    bằng giờ thật.
    """
    threshold = timezone.now() - discovery.LIVE_HEARTBEAT_WINDOW
    for run in DailyRun.objects.filter(status=DailyRun.Status.RUNNING):
        if _is_live(run, threshold):
            return run
    return None


def pause_stale_daily_runs() -> int:
    """Lượt "đang chạy" mà nhịp sống (của lượt lẫn lần quét con) đã cũ → bị gián đoạn → Tạm dừng.

    Người dùng đã bấm Dừng (ở trang lượt, hoặc ở trang lần quét con) nhưng app tắt trước khi luồng
    chạy kịp thấy → ghi là "bấm Dừng", không phải "bị gián đoạn", để không tự chạy tiếp ngược ý họ.
    """
    threshold = timezone.now() - discovery.LIVE_HEARTBEAT_WINDOW
    paused = 0
    for run in DailyRun.objects.filter(status=DailyRun.Status.RUNNING):
        if _is_live(run, threshold):
            continue
        if run.stop_requested or _child_stop_requested(run):
            kind, reason = DailyRun.PauseKind.STOPPED, REASON_STOPPED
        else:
            kind, reason = DailyRun.PauseKind.INTERRUPTED, REASON_INTERRUPTED
        paused += DailyRun.objects.filter(
            pk=run.pk, status=DailyRun.Status.RUNNING, heartbeat_at=run.heartbeat_at
        ).update(
            status=DailyRun.Status.PAUSED,
            pause_kind=kind,
            stop_reason=reason,
            paused_at=timezone.now(),
            runner_token="",
        )
    return paused


def close_previous_days(today: date) -> int:
    """Lượt của ngày trước `today` chưa xong (bị gián đoạn, đang Tạm dừng) → "Xong nhưng còn sót".

    Không cố chạy nốt lượt cũ: báo cáo tính theo ngày. Lượt cũ còn đang chạy thật thì để nó tự xong.
    Lần quét dở của lượt cũ vẫn Tạm dừng, tiếp tục bằng tay được ở trang lần quét đó.
    """
    threshold = timezone.now() - discovery.LIVE_HEARTBEAT_WINDOW
    closed = 0
    unfinished = DailyRun.objects.filter(
        day__lt=today, status__in=[DailyRun.Status.RUNNING, DailyRun.Status.PAUSED]
    )
    for run in unfinished:
        if _is_live(run, threshold):
            continue
        problems = [*run.problems, f"Hết ngày — lượt dừng ở bước «{run.get_step_display()}»."]
        closed += DailyRun.objects.filter(
            pk=run.pk, status=run.status, heartbeat_at=run.heartbeat_at
        ).update(
            status=DailyRun.Status.SUCCEEDED_PARTIAL,
            problems=problems,
            stop_reason=_summary(problems),
            pause_kind="",
            runner_token="",
            finished_at=timezone.now(),
        )
    return closed


# --- Bắt đầu, dừng, lịch ---------------------------------------------------------------------


def prepare_daily_run(*, now: datetime | None = None) -> DailyRun:
    """Bấm "Chạy ngay" / lệnh `daily`: tạo lượt hôm nay, hoặc mở lại lượt đang Tạm dừng / Lỗi.

    Lượt trả về đã giữ chỗ "đang chạy"; chạy thật bằng `execute_daily_run`. Từ chối
    (`DailyRunBlockedError`) khi đang có lần quét hay lượt khác chạy thật, hoặc hôm nay đã xong.
    Bấm trước 7:00 vẫn được: chỉ lịch tự động mới chờ 7:00.
    `now` là lúc bấm (quyết định ngày nào); nhịp sống luôn ghi bằng giờ thật.
    """
    moment = now if now is not None else timezone.now()
    today = timezone.localdate(moment)
    with transaction.atomic():
        close_previous_days(today)
        pause_stale_daily_runs()
        _ensure_nothing_live()
        run = DailyRun.objects.filter(day=today).first()
        if run is None:
            return DailyRun.objects.create(
                day=today,
                status=DailyRun.Status.RUNNING,
                step=DailyRun.Step.RESCAN,
                started_at=moment,
                heartbeat_at=timezone.now(),
            )
        if run.status in (DailyRun.Status.SUCCEEDED, DailyRun.Status.SUCCEEDED_PARTIAL):
            raise DailyRunBlockedError(
                f"Hôm nay đã quét xong ({run.get_status_display()}) — mỗi ngày chỉ một lượt, "
                "xem báo cáo ở trang Rising star."
            )
        reopened: dict[str, object] = {
            "status": DailyRun.Status.RUNNING,
            "runner_token": "",  # nhả mã: luồng cũ (nếu còn sống) thấy mất quyền và tự rút lui
            "stop_requested": False,
            "stop_reason": "",
            "pause_kind": "",
            "paused_at": None,
            "finished_at": None,
            "heartbeat_at": timezone.now(),
        }
        if run.status == DailyRun.Status.FAILED:
            reopened["error_message"] = ""
        DailyRun.objects.filter(pk=run.pk).update(**reopened)
        run.refresh_from_db()
    return run


def request_daily_stop(run: DailyRun) -> None:
    """Bấm Dừng ở trang lượt: luồng chạy dừng trước truy vấn kế tiếp.

    Đang quét lại thì dừng luôn lần quét con đang chạy. Lượt đang Tạm dừng chờ tự chạy tiếp thì
    thôi không tự chạy tiếp nữa. Lượt đã xong hoặc đã Lỗi thì không có gì để dừng.
    """
    DailyRun.objects.filter(
        pk=run.pk, status__in=[DailyRun.Status.RUNNING, DailyRun.Status.PAUSED]
    ).update(stop_requested=True)
    DailyRun.objects.filter(pk=run.pk, status=DailyRun.Status.PAUSED).update(
        pause_kind=DailyRun.PauseKind.STOPPED, stop_reason=REASON_STOPPED
    )
    run.refresh_from_db()
    if run.status != DailyRun.Status.RUNNING or run.step != DailyRun.Step.RESCAN:
        return
    children = run.scans.select_related("scan_run").filter(scan_run__status=ScanRun.Status.RUNNING)
    for link in children:
        if link.scan_run.is_live:
            discovery.request_stop(link.scan_run)


def release_unstarted_daily_run(run: DailyRun) -> None:
    """Lượt vừa giữ chỗ nhưng luồng nền đã bị việc khác chiếm → Tạm dừng, chờ bấm Chạy tiếp.

    Không để nó "đang chạy" nằm chờ sau một việc dài: nhịp sống sẽ cũ đi và nó bị coi là gián đoạn.
    Ghi là "bấm Dừng" (không phải gián đoạn) nên cũng không bị tự chạy tiếp.
    """
    DailyRun.objects.filter(pk=run.pk, status=DailyRun.Status.RUNNING, runner_token="").update(
        status=DailyRun.Status.PAUSED,
        pause_kind=DailyRun.PauseKind.STOPPED,
        stop_reason=REASON_BUSY_APP,
        paused_at=timezone.now(),
        heartbeat_at=None,
        runner_token="",
    )
    run.refresh_from_db()


def run_daily_if_due(*, now: datetime | None = None) -> DailyRun | None:
    """Việc định kỳ (trên luồng nền): đến lượt thì chạy lượt hôm nay tại chỗ, tới khi dừng.

    - Lượt ngày trước còn dở thì đóng lại; lượt "đang chạy" mà nhịp sống đã cũ thì coi là gián đoạn.
    - Đang có lần quét hay lượt chạy thật (kể cả ở cửa sổ khác) → chờ nhịp sau.
    - Lượt hôm nay bị gián đoạn, hoặc bị GitHub/mạng chặn từ 15 phút trở lên → tự chạy tiếp (tối đa
      3 lần).
    - Hôm nay chưa có lượt và đã quá 7:00 → bắt đầu (mở app muộn thì chạy bù ngay nhịp đầu).

    `now` chỉ dùng cho quyết định theo lịch; nhịp sống luôn so với giờ thật vì nó được ghi bằng giờ
    thật. Trả lượt vừa chạy, hoặc `None` nếu chưa đến lượt.
    """
    moment = now if now is not None else timezone.now()
    today = timezone.localdate(moment)
    close_previous_days(today)
    pause_stale_daily_runs()
    if discovery.live_scan() is not None or live_daily_run() is not None:
        return None
    run = DailyRun.objects.filter(day=today).first()
    if run is None:
        if timezone.localtime(moment).time() < DAILY_RUN_AFTER:
            return None
        try:
            run = prepare_daily_run(now=moment)
        except DailyRunBlockedError as exc:
            # Tiến trình khác vừa bắt đầu quét sau lần kiểm ở trên: chờ nhịp sau.
            logger.info("Chưa bắt đầu lượt hằng ngày: %s", exc)
            return None
    elif not _reopen_for_auto_continue(run, moment):
        return None
    logger.info("Chạy lượt quét hằng ngày %s", run.day)
    background.relabel(f"Lượt quét hằng ngày {run.day:%d/%m}")
    execute_daily_run(run.pk)
    run.refresh_from_db()
    return run


# --- Chạy lượt -------------------------------------------------------------------------------


def execute_daily_run(run_id: int) -> None:
    """Chạy lượt từ bước đang dở tới khi xong, tạm dừng hoặc lỗi. Gọi từ luồng nền hoặc lệnh."""
    token = uuid.uuid4().hex
    claimed = DailyRun.objects.filter(
        pk=run_id, status=DailyRun.Status.RUNNING, runner_token=""
    ).update(runner_token=token, heartbeat_at=timezone.now())
    if not claimed:
        logger.info(
            "Bỏ qua lượt hằng ngày #%s: không ở trạng thái chạy hoặc đã có luồng khác giữ", run_id
        )
        return
    runner = _DailyRunner(run_id, token=token)
    try:
        runner.run()
    except DailySupersededError:
        logger.info("Lượt hằng ngày #%s: luồng cũ rút lui, không ghi gì thêm", run_id)
    except KeyboardInterrupt:
        runner.pause(DailyRun.PauseKind.STOPPED, REASON_CTRL_C)
        raise
    except Exception as exc:
        logger.exception("Lượt hằng ngày #%s gặp lỗi không mong đợi", run_id)
        runner.fail(f"{_UNEXPECTED_REASON} (Chi tiết: {exc!r})")
        raise


class _DailyRunner:
    """Một luồng chạy lượt. Mọi lần ghi đều kèm điều kiện "còn giữ lượt" (`runner_token`)."""

    def __init__(self, run_id: int, *, token: str) -> None:
        self.run_id = run_id
        self.token = token

    def run(self) -> None:
        """Làm tiếp từ bước đang dở.

        Xong một bước mới ghi bước kế: sập giữa chừng thì lần sau làm lại đúng bước đó.
        """
        run = self._check_in()
        if run.step == DailyRun.Step.RESCAN:
            if not self._rescan():
                return
            run = self._check_in(step=DailyRun.Step.SCREEN)
        if run.step == DailyRun.Step.SCREEN:
            self._screen()
            run = self._load()
        if run.step == DailyRun.Step.VERIFY:
            if not self._verify():
                return
            run = self._load()
        if run.step == DailyRun.Step.OWNERS:
            if not self._owners():
                return
            run = self._load()
        if run.step == DailyRun.Step.CLASSIFY:
            self._classify()
        self._report()

    # --- Bước 1: quét lại danh sách theo dõi -------------------------------------------------

    def _rescan(self) -> bool:
        """Mỗi truy vấn đang bật là một lần quét sâu, chạy lần lượt. `False` = lượt phải dừng."""
        watch_ids = list(WatchQuery.objects.filter(enabled=True).values_list("pk", flat=True))
        for index, watch_id in enumerate(watch_ids, start=1):
            run = self._check_in()
            if run.stop_requested:
                self.pause(DailyRun.PauseKind.STOPPED, REASON_STOPPED)
                return False
            # Đọc lại từng truy vấn: người dùng có thể xoá hoặc tắt nó trong lúc lượt đang chạy.
            watch = WatchQuery.objects.filter(pk=watch_id, enabled=True).first()
            if watch is None:
                continue
            logger.info(
                "Lượt hằng ngày %s: quét lại «%s» (%s/%s)",
                run.day,
                watch.query,
                index,
                len(watch_ids),
            )
            if not self._rescan_one(run, watch):
                return False
        self._note_left_behind()
        self._update(**self._totals(), heartbeat_at=timezone.now())
        return True

    def _rescan_one(self, run: DailyRun, watch: WatchQuery) -> bool:
        # Xét lần quét mới nhất của truy vấn: lần quét lỗi token / lỗi code được thay bằng lần mới.
        links = run.scans.select_related("scan_run").filter(watch_query=watch)
        link = links.order_by("-position", "-pk").first()
        if link is None or _needs_new_scan(link.scan_run):
            try:
                scan = self._start_scan(run, watch)
            except discovery.ScanAlreadyRunningError as exc:
                self.pause(DailyRun.PauseKind.RETRY_LATER, _busy_reason(exc.scan))
                return False
        else:
            scan = link.scan_run
            if scan.status in _SCAN_FINISHED:
                self._note(scan)  # đã xong ở lần chạy trước: không quét lại
                return True
            if scan.is_live:
                self.pause(DailyRun.PauseKind.RETRY_LATER, _busy_reason(scan))
                return False
            try:
                discovery.resume_scan(scan, extra_budget=0)
            except discovery.ScanAlreadyRunningError as exc:
                self.pause(DailyRun.PauseKind.RETRY_LATER, _busy_reason(exc.scan))
                return False
        discovery.execute_scan(scan.pk)
        self._check_in(**self._totals())
        scan.refresh_from_db()
        return self._after_child(scan)

    def _start_scan(self, run: DailyRun, watch: WatchQuery) -> ScanRun:
        request = discovery.ScanRequest(
            query=watch.query,
            min_stars=watch.min_stars,
            max_stars=watch.max_stars,
            created_from=None,
            created_to=None,
            budget=watch.budget,
            origin=ScanRun.Origin.DAILY,
        )
        # Lần quét và liên kết tới lượt ghi cùng lúc: app tắt giữa hai việc thì không để lại lần
        # quét mồ côi mà lượt không biết để nối lại.
        with transaction.atomic():
            scan = discovery.start_scan(request)
            # Lớn nhất + 1 chứ không phải số liên kết + 1: liên kết nào mất đi (lần quét bị xoá) thì
            # thứ tự mới vẫn không trùng thứ tự cũ.
            top = run.scans.aggregate(top=Max("position"))["top"] or 0
            DailyRunScan.objects.create(
                daily_run=run, watch_query=watch, scan_run=scan, position=top + 1
            )
        return scan

    def _after_child(self, scan: ScanRun) -> bool:
        """Xử lý kết quả lần quét con theo bảng ở mục 5 của thiết kế. `False` = lượt phải dừng."""
        if scan.status == ScanRun.Status.FAILED and scan.error_kind == ScanRun.ErrorKind.AUTH:
            # Token sai / hết quyền: truy vấn nào cũng sẽ hỏng như vậy → dừng cả lượt.
            self.fail(f"Truy vấn «{scan.query}» (lần quét #{scan.pk}): {scan.error_message}")
            return False
        if scan.status in _SCAN_FINISHED:
            self._note(scan)
            return True
        if scan.status == ScanRun.Status.PAUSED and scan.stop_reason == discovery.REASON_STOPPED:
            self.pause(DailyRun.PauseKind.STOPPED, REASON_STOPPED)
        elif scan.status == ScanRun.Status.PAUSED and _blocked_by_github(scan.stop_reason):
            reason = REASON_BLOCKED.format(
                query=scan.query, scan_id=scan.pk, minutes=_RETRY_MINUTES
            )
            self.pause(DailyRun.PauseKind.RETRY_LATER, reason)
        else:
            # Tạm dừng vì lý do khác (vd tiến trình khác coi nó là gián đoạn), hoặc luồng khác giữ.
            self.pause(DailyRun.PauseKind.INTERRUPTED, REASON_INTERRUPTED)
        return False

    def _note_left_behind(self) -> None:
        """Lần quét dở của truy vấn đã bị tắt hoặc xoá (lúc lượt đang dừng) → ghi lại, không bỏ rơi.

        Sau vòng quét lại, mọi truy vấn đang bật đều đã xong lần quét mới nhất của nó; lần quét còn
        dở chỉ có thể thuộc truy vấn không còn được quét nữa.
        """
        leftovers = DailyRunScan.objects.filter(
            daily_run_id=self.run_id, scan_run__status__in=_SCAN_UNFINISHED
        ).select_related("scan_run")
        for link in leftovers:
            scan = link.scan_run
            self._add_problem(
                f"Truy vấn «{scan.query}» (lần quét #{scan.pk}) đã tắt hoặc bị xoá khỏi danh sách "
                "theo dõi — lần quét còn dở, tiếp tục bằng tay ở trang lần quét đó được."
            )

    def _note(self, scan: ScanRun) -> None:
        """Lần quét con xong mà còn sót hoặc lỗi → ghi vào `problems` (ghi một lần dù chạy tiếp)."""
        if scan.status == ScanRun.Status.SUCCEEDED_PARTIAL:
            self._add_problem(
                f"Truy vấn «{scan.query}» (lần quét #{scan.pk}) còn sót: {scan.stop_reason}"
            )
        elif scan.status == ScanRun.Status.FAILED:
            self._add_problem(
                f"Truy vấn «{scan.query}» (lần quét #{scan.pk}) lỗi: {scan.error_message}"
            )

    # --- Bước 2: lọc thô bằng ảnh chụp (không tốn lượt gọi) -----------------------------------

    def _screen(self) -> None:
        """Ước lượng mức tăng 7 ngày của mọi repo vừa thấy; từ ngưỡng lọc thô trở lên là ứng viên.

        Ghi ứng viên và chuyển bước trong cùng một transaction; sập giữa chừng thì lần sau lọc lại
        từ đầu, xoá dòng ước lượng cũ của lượt trước khi ghi mới (không sinh dòng trùng).
        """
        self._check_in()
        now = timezone.now()
        # DEBT(D-009): ngày lấy theo đồng hồ, không theo run.day (lượt vắt qua 0:00 lệch một ngày).
        today = timezone.localdate(now)
        scan_ids = list(
            DailyRunScan.objects.filter(daily_run_id=self.run_id).values_list(
                "scan_run_id", flat=True
            )
        )
        baselines = catalog.baseline_snapshots(today=today)
        # Fork, repo đã lưu trữ, repo từ 1.000 star không thể là rising star → không xét.
        seen = (
            discovery.repositories_seen_in(scan_ids)
            .filter(stars__lt=growth.RISING_MAX_STARS, is_fork=False, is_archived=False)
            .order_by("pk")
            .values_list("pk", "stars", "gh_created_at")
        )
        candidates: list[RisingCheck] = []
        insufficient = 0
        for repository_id, stars, created_at in seen.iterator():
            baseline = baselines.get(repository_id)
            estimate = growth.estimate_gain_7d(
                stars_now=stars,
                baseline=baseline,
                today=today,
                created_on=timezone.localdate(created_at),
            )
            if estimate is None:
                insufficient += 1
            elif estimate >= growth.CANDIDATE_MIN_ESTIMATE_7D:
                candidates.append(
                    RisingCheck(
                        daily_run_id=self.run_id,
                        repository_id=repository_id,
                        stars=stars,
                        source=(
                            RisingCheck.Source.AGE
                            if baseline is None
                            else RisingCheck.Source.SNAPSHOT
                        ),
                        gain_7d=estimate,
                        baseline_day=None if baseline is None else baseline.day,
                    )
                )
        with transaction.atomic():
            RisingCheck.objects.filter(daily_run_id=self.run_id).exclude(
                source=RisingCheck.Source.HISTORY
            ).delete()
            RisingCheck.objects.bulk_create(candidates)
            self._check_in(
                step=DailyRun.Step.VERIFY,
                candidate_count=len(candidates),
                insufficient_count=insufficient,
                window_end=growth.last_complete_utc_day(now),
            )
        logger.info(
            "Lượt hằng ngày #%s: lọc thô xong — %s ứng viên, %s repo chưa đủ dữ liệu",
            self.run_id,
            len(candidates),
            insufficient,
        )

    # --- Bước 3: xác minh bằng lịch sử star chính thức ---------------------------------------

    def _verify(self) -> bool:
        """Xác minh ứng viên bằng lịch sử star. `False` = lượt phải dừng (tạm dừng hoặc lỗi).

        Mỗi ứng viên chưa xác minh tốn một lượt gọi, ước lượng lớn trước, tới khi hết ngân sách.
        Dòng đã xác minh (kể cả ở lần chạy trước) không bao giờ bị gọi lại.
        """
        run = self._check_in()
        if run.verify_budget == 0:
            # Chốt ngân sách một lần lúc bắt đầu xác minh: chạy tiếp vẫn giữ ngân sách ban đầu.
            run = self._check_in(verify_budget=_verify_budget())
        pending = list(
            RisingCheck.objects.filter(daily_run_id=self.run_id)
            .exclude(source=RisingCheck.Source.HISTORY)
            .order_by("-gain_7d", "pk")
            .values_list("pk", flat=True)
        )
        if pending and not self._verify_rows(run, pending):
            return False
        self._check_in(step=DailyRun.Step.OWNERS)
        return True

    def _verify_rows(self, run: DailyRun, pending: list[int]) -> bool:
        window_end = run.window_end
        if window_end is None:
            raise RuntimeError(f"Lượt #{self.run_id} ở bước xác minh mà chưa chốt cửa sổ ngày UTC.")
        calls_before = run.verify_calls_used
        budget = CallBudget(max(0, run.verify_budget - calls_before))
        sleep = _HeartbeatSleep(self._beat_or_stop)
        try:
            with get_github_client(sleep=sleep, budget=budget) as github:
                for index, check_id in enumerate(pending, start=1):
                    self._beat_or_stop()
                    self._verify_one(
                        github,
                        check_id,
                        budget=budget,
                        calls_before=calls_before,
                        window_end=window_end,
                    )
                    logger.info(
                        "Lượt hằng ngày #%s: đã xét %s/%s ứng viên, lượt gọi xác minh %s/%s",
                        self.run_id,
                        index,
                        len(pending),
                        calls_before + budget.used,
                        run.verify_budget,
                    )
        except CallBudgetExhaustedError:
            left = (
                RisingCheck.objects.filter(daily_run_id=self.run_id)
                .exclude(source=RisingCheck.Source.HISTORY)
                .count()
            )
            self._add_problem(VERIFY_BUDGET_NOTE.format(count=left))
        except _DailyStopRequestedError:
            self.pause(DailyRun.PauseKind.STOPPED, REASON_STOPPED)
            return False
        except (GitHubRateLimitError, GitHubUnavailableError) as exc:
            logger.warning("Lượt hằng ngày #%s: GitHub chặn lúc xác minh: %r", self.run_id, exc)
            reason = REASON_VERIFY_BLOCKED.format(minutes=_RETRY_MINUTES)
            self.pause(DailyRun.PauseKind.RETRY_LATER, reason)
            return False
        except GitHubAuthError as exc:
            logger.warning("Lượt hằng ngày #%s: GitHub từ chối token: %r", self.run_id, exc)
            self.fail(REASON_VERIFY_AUTH.format(detail=exc))
            return False
        return True

    def _verify_one(
        self,
        github: GitHubClient,
        check_id: int,
        *,
        budget: CallBudget,
        calls_before: int,
        window_end: date,
    ) -> None:
        check = (
            RisingCheck.objects.select_related("repository")
            .filter(pk=check_id)
            .exclude(source=RisingCheck.Source.HISTORY)
            .first()
        )
        if check is None:
            return
        repository = check.repository
        try:
            history = self._fetch_history(
                github, repository.github_id, budget=budget, calls_before=calls_before
            )
        except GitHubNotFoundError:
            logger.info(
                "Lượt hằng ngày #%s: %s không còn trên GitHub (404) — bỏ khỏi danh sách xét",
                self.run_id,
                repository.full_name,
            )
            with transaction.atomic():
                self._update(heartbeat_at=timezone.now())  # còn giữ lượt mới được xoá
                RisingCheck.objects.filter(pk=check.pk).delete()
            return
        except (GitHubResponseError, GitHubQueryError) as exc:
            logger.warning(
                "Lượt hằng ngày #%s: lịch sử star của %s không đọc được: %r",
                self.run_id,
                repository.full_name,
                exc,
            )
            self._add_problem(UNREADABLE_HISTORY_NOTE.format(repo=repository.full_name, detail=exc))
            return
        self._save_history(check, history, window_end=window_end)

    def _fetch_history(
        self, github: GitHubClient, github_id: int, *, budget: CallBudget, calls_before: int
    ) -> StarHistory:
        try:
            return github.star_history(github_id)
        finally:
            # Ghi ngay sau mỗi lượt gọi, kể cả khi lỗi hay app sập: lượt gọi đã tiêu thì không được
            # "hoàn" vào ngân sách khi chạy tiếp. Không ném lỗi ở đây để không che lỗi gốc.
            self._owned().update(verify_calls_used=calls_before + budget.used)

    def _save_history(self, check: RisingCheck, history: StarHistory, *, window_end: date) -> None:
        gains = growth.growth_from_history(history, window_end=window_end)
        repository = check.repository
        age_days = (timezone.localdate() - timezone.localdate(repository.gh_created_at)).days
        flags = growth.warning_flags(
            series=gains.series, age_days=age_days, description=repository.description
        )
        with transaction.atomic():
            self._update(heartbeat_at=timezone.now())  # còn giữ lượt mới được ghi
            RisingCheck.objects.filter(pk=check.pk).update(
                source=RisingCheck.Source.HISTORY,
                gain_1d=gains.gain_1d,
                gain_7d=gains.gain_7d,
                gain_30d=gains.gain_30d,
                series=list(gains.series),
                window_end=window_end,
                is_rising=growth.is_rising(check.stars, gains.gain_7d),
                flags=[flag.value for flag in flags],
            )

    # --- Bước 4: lấy hồ sơ chủ của rising star (F-006) ------------------------------------------

    def _owners(self) -> bool:
        """Lấy hồ sơ chủ của rising star chưa có hồ sơ (hoặc hồ sơ quá 30 ngày). `False` = dừng.

        Chủ của repo đang bị nghi star giả (từ "Cần xem") được lấy trước: chỉ ở đó hồ sơ chủ mới đổi
        được kết luận, mà không token thì mỗi ngày chỉ lấy được 10 hồ sơ. Trong mỗi nhóm, repo tăng
        nhiều trước. Hồ sơ lưu ngay sau mỗi lượt gọi nên chạy tiếp không gọi lại; hết ngân sách chỉ
        ghi chú, không phải lỗi.
        """
        run = self._check_in()
        if run.owner_budget == 0:
            # Chốt ngân sách một lần lúc bắt đầu bước: chạy tiếp vẫn giữ ngân sách ban đầu.
            run = self._check_in(owner_budget=_owner_budget())
        checks = list(
            RisingCheck.objects.filter(daily_run_id=self.run_id, is_rising=True)
            .select_related("repository")
            .order_by("-gain_7d", "pk")
        )
        scores = scoring.score_repositories(
            [check.repository for check in checks],
            growth={check.repository_id: _growth_facts(check) for check in checks},
        )
        # Sắp ổn định: nhóm đang bị nghi lên trước, trong nhóm giữ thứ tự tăng nhiều trước.
        checks.sort(key=lambda check: scores[check.repository_id].suspicion.points < REVIEW_FROM)
        logins = [check.repository.owner_login for check in checks]
        pending = scoring.owners_to_fetch(logins, now=timezone.now())
        if pending:
            self._fetch_owners(run, pending)
        self._check_in(step=DailyRun.Step.CLASSIFY)
        return True

    def _fetch_owners(self, run: DailyRun, pending: list[str]) -> None:
        """Gọi GitHub lấy từng hồ sơ. Hỏng giữa chừng thì ghi chú rồi thôi — không chặn báo cáo.

        Bước này chỉ làm giàu dữ liệu (nguyên tắc 8): bấm Dừng, GitHub chặn hay từ chối token thì
        dừng gọi, ghi lại số chủ còn thiếu (lượt hôm sau lấy tiếp) và đi tiếp tới lập báo cáo —
        bước đó chỉ đọc CSDL nên xong ngay. Không để lượt kẹt ở đây rồi mất báo cáo khi hết ngày.
        """
        calls_before = run.owner_calls_used
        budget = CallBudget(max(0, run.owner_budget - calls_before))

        def record_calls() -> None:
            # Ghi sau mỗi lượt gọi, kể cả khi lỗi hay app sập: lượt đã tiêu không được "hoàn".
            self._owned().update(owner_calls_used=calls_before + budget.used)

        try:
            with get_github_client(sleep=_HeartbeatSleep(self._beat_or_stop), budget=budget) as gh:
                outcome = scoring.fetch_owner_profiles(
                    gh, pending, before_each=self._beat_or_stop, after_call=record_calls
                )
        except CallBudgetExhaustedError:
            left = len(scoring.owners_to_fetch(pending, now=timezone.now()))
            self._add_problem(OWNER_BUDGET_NOTE.format(count=left))
            return
        except _DailyStopRequestedError:
            self._note_owners_left(pending, _OWNERS_STOPPED)
            return
        except (GitHubRateLimitError, GitHubUnavailableError) as exc:
            logger.warning(
                "Lượt hằng ngày #%s: GitHub chặn lúc lấy hồ sơ chủ: %r", self.run_id, exc
            )
            self._note_owners_left(pending, _OWNERS_BLOCKED)
            return
        except GitHubAuthError as exc:
            logger.warning("Lượt hằng ngày #%s: GitHub từ chối token: %r", self.run_id, exc)
            self._note_owners_left(pending, _OWNERS_AUTH)
            return
        for login, detail in outcome.unreadable:
            self._add_problem(UNREADABLE_OWNER_NOTE.format(login=login, detail=detail))
        logger.info(
            "Lượt hằng ngày #%s: hồ sơ chủ repo — lấy %s, không còn tồn tại %s, lỗi %s",
            self.run_id,
            outcome.fetched,
            outcome.missing,
            len(outcome.unreadable),
        )

    def _note_owners_left(self, pending: list[str], detail: str) -> None:
        left = len(scoring.owners_to_fetch(pending, now=timezone.now()))
        self._add_problem(OWNERS_BLOCKED_NOTE.format(count=left, detail=detail))

    # --- Bước 5: phân loại repo của lượt bằng AI (F-010) ---------------------------------------

    def _classify(self) -> None:
        """Gắn nhãn cho repo của lượt (rising star trước). Chưa có khoá AI thì bỏ qua.

        Chỉ làm giàu dữ liệu (nguyên tắc 8): hỏng gì (9router tắt, khoá sai, bấm Dừng, đang có lần
        phân loại khác) cũng ghi chú rồi đi tiếp lập báo cáo. Hết ngân sách không phải lỗi: phần còn
        lại do việc định kỳ phân loại dần.
        """
        self._check_in()
        if llm_configured():
            self._classify_repos()
        self._check_in(step=DailyRun.Step.REPORT)

    def _classify_repos(self) -> None:
        in_run = Repository.objects.filter(rising_checks__daily_run_id=self.run_id)
        repos = taxonomy.repositories_needing_labels(among=in_run)
        if not repos:
            return
        order = list(
            RisingCheck.objects.filter(daily_run_id=self.run_id)
            .order_by("-is_rising", "-gain_7d", "pk")
            .values_list("repository_id", flat=True)
        )
        rank = {repository_id: index for index, repository_id in enumerate(order)}
        repos.sort(key=lambda repo: rank.get(repo.pk, len(rank)))
        try:
            classify_run = taxonomy.start_classify_run(taxonomy.Origin.DAILY)
        except taxonomy.ClassifyBusyError:
            self._add_problem(CLASSIFY_BLOCKED_NOTE.format(detail=_CLASSIFY_BUSY, count=len(repos)))
            return
        error = ""
        budget = CallBudget(DAILY_RUN_CLASSIFY_CALLS)
        try:
            with get_llm_client(sleep=_HeartbeatSleep(self._beat_or_stop), budget=budget) as llm:
                taxonomy.classify(classify_run, repos, llm=llm, before_each=self._beat_or_stop)
        except CallBudgetExhaustedError:
            logger.info(
                "Lượt hằng ngày #%s: hết lượt phân loại trong lượt — phân loại dần sau", self.run_id
            )
        except _DailyStopRequestedError:
            error = _OWNERS_STOPPED
        except LlmError as exc:
            logger.warning("Lượt hằng ngày #%s: phân loại bằng AI hỏng: %r", self.run_id, exc)
            error = str(exc)
        finally:
            taxonomy.finish_classify_run(classify_run, error=error)
            # Ghi cả khi lỗi; không ném lỗi ở đây để không che lỗi gốc.
            self._owned().update(ai_calls_used=F("ai_calls_used") + classify_run.calls_used)
        if error:
            left = len(taxonomy.repositories_needing_labels(among=in_run))
            self._add_problem(CLASSIFY_BLOCKED_NOTE.format(detail=error, count=left))

    def _beat_or_stop(self) -> None:
        """Ghi nhịp sống ở bước xác minh; người dùng đã bấm Dừng thì thôi, kể cả đang chờ GitHub."""
        if self._check_in().stop_requested:
            raise _DailyStopRequestedError

    # --- Bước 6: lập báo cáo, dọn dữ liệu cũ -------------------------------------------------

    def _report(self) -> None:
        """Ghi số rising / chưa xác minh, dọn dữ liệu quá hạn giữ, rồi kết thúc lượt.

        Dọn dữ liệu làm lại bao nhiêu lần cũng vậy: sập giữa chừng thì lần sau làm lại cả bước.
        """
        checks = RisingCheck.objects.filter(daily_run_id=self.run_id)
        self._check_in(
            rising_count=checks.filter(is_rising=True).count(),
            unverified_count=checks.exclude(source=RisingCheck.Source.HISTORY).count(),
        )
        now = timezone.now()
        snapshots = catalog.prune_snapshots(
            before=timezone.localdate(now) - timedelta(days=RETENTION_DAYS)
        )
        results = discovery.prune_daily_results(before=now - timedelta(days=RETENTION_DAYS))
        # Điểm lưu sẵn cho trang Kho repo (QĐ-19): cả kho mỗi ngày ~3 giây, sau khi đã có số liệu
        # mới của các lần quét và hồ sơ chủ của lượt.
        scored = scoring.refresh_scores()
        logger.info("Lượt hằng ngày #%s: đã tính lại điểm lưu sẵn cho %s repo", self.run_id, scored)
        logger.info(
            "Lượt hằng ngày #%s: đã dọn %s ảnh chụp và %s dòng kết quả quét quá %s ngày",
            self.run_id,
            snapshots,
            results,
            RETENTION_DAYS,
        )
        self._finish()

    # --- Kết cục -----------------------------------------------------------------------------

    def pause(self, kind: DailyRun.PauseKind, reason: str) -> None:
        """Tạm dừng lượt. Người dùng đã bấm Dừng thì ghi là "bấm Dừng": không tự chạy tiếp."""
        stop_requested = DailyRun.objects.filter(pk=self.run_id, stop_requested=True).exists()
        if stop_requested and kind != DailyRun.PauseKind.STOPPED:
            kind, reason = DailyRun.PauseKind.STOPPED, REASON_STOPPED
        self._write_outcome(
            status=DailyRun.Status.PAUSED,
            pause_kind=kind,
            stop_reason=reason,
            paused_at=timezone.now(),
        )

    def fail(self, error: str) -> None:
        self._write_outcome(
            status=DailyRun.Status.FAILED, error_message=error, finished_at=timezone.now()
        )

    def _finish(self) -> None:
        run = self._load()
        problems = list(run.problems)
        status = DailyRun.Status.SUCCEEDED_PARTIAL if problems else DailyRun.Status.SUCCEEDED
        reason = _summary(problems)
        if not problems and not run.scans.exists():
            # Danh sách theo dõi trống không làm sót gì → vẫn Xong, chỉ nhắc thêm truy vấn.
            reason = EMPTY_WATCH_LIST_NOTE
        self._write_outcome(
            status=status,
            stop_reason=reason,
            stop_requested=False,
            finished_at=timezone.now(),
        )

    def _write_outcome(self, **fields: object) -> None:
        """Ghi kết cục (kèm tổng lượt gọi) và nhả quyền giữ lượt; mất quyền rồi thì không ghi gì.

        Không ném `DailySupersededError`: hàm còn được gọi trong lúc xử lý Ctrl+C và lỗi bất ngờ.
        """
        self._owned().update(
            **self._totals(), **fields, runner_token="", heartbeat_at=timezone.now()
        )

    # --- Ghi có điều kiện ----------------------------------------------------------------------

    def _check_in(self, **fields: object) -> DailyRun:
        """Ghi nhịp sống (và `fields`) rồi đọc lại lượt; mất quyền giữ lượt thì rút lui."""
        self._update(**fields, heartbeat_at=timezone.now())
        return self._load()

    def _add_problem(self, note: str) -> None:
        problems = list(self._load().problems)
        if note not in problems:
            self._update(problems=[*problems, note])

    def _totals(self) -> dict[str, int]:
        """Tổng lượt gọi Search và số repo mới của các lần quét con.

        Luôn cộng lại từ đầu thay vì cộng dồn: chạy tiếp bao nhiêu lần cũng không bị cộng trùng.
        """
        sums = DailyRunScan.objects.filter(daily_run_id=self.run_id).aggregate(
            calls=Sum("scan_run__api_calls_used"), created=Sum("scan_run__created_count")
        )
        return {"search_calls_used": sums["calls"] or 0, "new_repo_count": sums["created"] or 0}

    def _load(self) -> DailyRun:
        run = self._owned().first()
        if run is None:
            raise DailySupersededError
        return run

    def _update(self, **fields: object) -> None:
        if not self._owned().update(**fields):
            raise DailySupersededError

    def _owned(self) -> QuerySet[DailyRun]:
        return DailyRun.objects.filter(
            pk=self.run_id, runner_token=self.token, status=DailyRun.Status.RUNNING
        )


# --- Hàm phụ ---------------------------------------------------------------------------------


def _is_live(run: DailyRun, threshold: datetime) -> bool:
    if run.status != DailyRun.Status.RUNNING:
        return False
    if run.heartbeat_at is not None and run.heartbeat_at >= threshold:
        return True
    # Từ bước lọc thô trở đi, lượt tự ghi nhịp sống: lần quét con đang chạy lúc đó (vd lần quét bị
    # bỏ lại được bấm Tiếp tục bằng tay) không được giữ một lượt đã chết là "còn sống".
    if run.step != DailyRun.Step.RESCAN:
        return False
    # Xét nhịp sống của lần quét con bất kể trạng thái: lần quét con vừa xong (nhịp sống còn mới)
    # mà lượt chưa kịp ghi nhịp sống của mình thì lượt vẫn đang chạy, không phải bị gián đoạn.
    return run.scans.filter(scan_run__heartbeat_at__gte=threshold).exists()


def _child_stop_requested(run: DailyRun) -> bool:
    """Lần quét con làm gần nhất đã bị bấm Dừng, mà app tắt trước khi lượt kịp ghi "Tạm dừng".

    Hai cách bị lỡ: lần quét con chưa kịp thấy cờ Dừng (cờ còn nguyên), hoặc đã dừng xong theo cờ
    nhưng lượt chưa kịp xử lý kết quả đó. Chỉ xét lần quét làm gần nhất, và chỉ khi lượt còn ở bước
    quét lại: lần quét dở cũ (của truy vấn đã tắt) không được biến lần gián đoạn sau thành
    "bấm Dừng".
    """
    if run.step != DailyRun.Step.RESCAN:
        return False
    latest = (
        run.scans.select_related("scan_run")
        .order_by(F("scan_run__heartbeat_at").desc(nulls_last=True), "-position", "-pk")
        .first()
    )
    if latest is None:
        return False
    scan = latest.scan_run
    if scan.status in _SCAN_UNFINISHED and scan.stop_requested:
        return True
    return scan.status == ScanRun.Status.PAUSED and scan.stop_reason == discovery.REASON_STOPPED


def _needs_new_scan(scan: ScanRun) -> bool:
    return scan.status == ScanRun.Status.FAILED and scan.error_kind in _RESCAN_ERROR_KINDS


def _ensure_nothing_live() -> None:
    live_run = live_daily_run()
    if live_run is not None:
        raise DailyRunBlockedError(f"Lượt quét hằng ngày {live_run.day:%d/%m} đang chạy.")
    scan = discovery.live_scan()
    if scan is not None:
        raise DailyRunBlockedError(
            f"Đang có lần quét #{scan.pk} chạy — chờ nó xong (hoặc bấm Dừng ở trang lần quét đó) "
            "rồi chạy lại."
        )


def _reopen_for_auto_continue(run: DailyRun, moment: datetime) -> bool:
    """Lượt hôm nay bị gián đoạn / bị chặn đủ lâu và còn lượt tự chạy tiếp → mở lại để chạy tiếp."""
    if run.status != DailyRun.Status.PAUSED or run.stop_requested:
        return False
    if run.auto_continue_count >= MAX_AUTO_CONTINUES:
        return False
    if run.pause_kind == DailyRun.PauseKind.RETRY_LATER:
        if run.paused_at is not None and run.paused_at > moment - RETRY_LATER_AFTER:
            return False
    elif run.pause_kind != DailyRun.PauseKind.INTERRUPTED:
        return False
    # Đếm cùng lúc với mở lại, TRƯỚC khi chạy: lượt làm sập app vẫn bị đếm, không lặp mãi.
    reopened = DailyRun.objects.filter(
        pk=run.pk,
        status=DailyRun.Status.PAUSED,
        stop_requested=False,
        auto_continue_count=run.auto_continue_count,
    ).update(
        status=DailyRun.Status.RUNNING,
        runner_token="",
        pause_kind="",
        stop_reason="",
        paused_at=None,
        heartbeat_at=timezone.now(),
        auto_continue_count=F("auto_continue_count") + 1,
        last_auto_continue_at=moment,
    )
    return reopened == 1


def _blocked_by_github(stop_reason: str) -> bool:
    return stop_reason == discovery.REASON_WAIT_TOO_LONG or stop_reason.startswith(
        _CONNECTION_PREFIX
    )


def _busy_reason(scan: ScanRun) -> str:
    return REASON_BUSY.format(scan_id=scan.pk, minutes=_RETRY_MINUTES)


def _summary(problems: list[str]) -> str:
    return "\n".join(problems)


def _verify_budget() -> int:
    return VERIFY_BUDGET_WITH_TOKEN if settings.GITHUB_TOKEN else VERIFY_BUDGET_ANONYMOUS


def classify_backlog_if_due(*, now: datetime | None = None) -> int:
    """Việc định kỳ: phân loại dần phần kho chưa có nhãn. Trả số lượt gọi AI đã dùng ở nhịp này.

    Chỉ chạy khi: đã có khoá AI, lượt hằng ngày hôm nay đã xong (không tranh luồng nền với lượt),
    chưa dùng hết `LLM_BACKLOG_CALLS_PER_DAY` lượt hôm nay, và lần trước không vừa lỗi (nghỉ 30
    phút — không gọi dồn khi 9router tắt hay khoá sai). Mỗi nhịp tối đa `BACKLOG_CALLS_PER_TICK`
    lượt để luồng nền không bị giữ lâu.
    """
    if not llm_configured():
        return 0
    moment = now if now is not None else timezone.now()
    today = timezone.localdate(moment)
    run = DailyRun.objects.filter(day=today).first()
    if run is None or run.status not in (
        DailyRun.Status.SUCCEEDED,
        DailyRun.Status.SUCCEEDED_PARTIAL,
    ):
        return 0
    left = settings.LLM_BACKLOG_CALLS_PER_DAY - taxonomy.ai_calls_on(
        today, origin=taxonomy.Origin.BACKLOG
    )
    if left <= 0:
        return 0
    failed_at = taxonomy.last_failure_at(taxonomy.Origin.BACKLOG)
    if failed_at is not None and failed_at > moment - BACKLOG_PAUSE_AFTER_ERROR:
        return 0
    repos = taxonomy.repositories_needing_labels()
    if not repos:
        return 0
    try:
        classify_run = taxonomy.start_classify_run(taxonomy.Origin.BACKLOG)
    except taxonomy.ClassifyBusyError:
        return 0
    background.relabel("Phân loại dần kho repo bằng AI")
    calls = min(BACKLOG_CALLS_PER_TICK, left)
    error = ""
    try:
        with get_llm_client(budget=CallBudget(calls)) as llm:
            taxonomy.classify(classify_run, repos[: calls * taxonomy.BATCH_SIZE], llm=llm)
    except CallBudgetExhaustedError:
        logger.info("Phân loại dần: hết %s lượt của nhịp này", calls)
    except LlmError as exc:
        logger.warning("Phân loại dần kho bị ngắt, nghỉ 30 phút: %r", exc)
        error = str(exc)
    finally:
        taxonomy.finish_classify_run(classify_run, error=error)
    return classify_run.calls_used


def _owner_budget() -> int:
    return OWNER_BUDGET_WITH_TOKEN if settings.GITHUB_TOKEN else OWNER_BUDGET_ANONYMOUS


class _HeartbeatSleep:
    """Hàm ngủ cho client GitHub ở bước xác minh: ngủ từng khúc ≤ 10 giây, sau mỗi khúc gọi `beat`.

    `beat` ghi nhịp sống của lượt (chờ GitHub hồi lượt có khi vài phút) và ném lỗi khi người dùng
    bấm Dừng hoặc luồng này mất quyền giữ lượt — để thôi chờ ngay.
    """

    def __init__(
        self, beat: Callable[[], None], *, chunk: float = discovery.HEARTBEAT_CHUNK_SECONDS
    ) -> None:
        self._beat = beat
        self._chunk = chunk

    def __call__(self, seconds: float) -> None:
        remaining = seconds
        while remaining > 0:
            step = min(self._chunk, remaining)
            time.sleep(step)
            remaining -= step
            self._beat()


# --- Đọc báo cáo -----------------------------------------------------------------------------


# Thứ tự bảng rising star: theo điểm Tiềm năng (mặc định, F-006) hoặc theo số tăng 7 ngày.
SORT_POTENTIAL = "potential"
SORT_GAIN = "gain"


@dataclass(frozen=True, slots=True)
class RisingRow:
    """Một dòng của bảng rising star, kèm sẵn mọi thứ trang cần hiện (không tính trong template)."""

    check: RisingCheck
    repository: Repository
    is_new_entry: bool
    growth_percent: float | None
    age_days: int
    flag_labels: tuple[str, ...]
    sparkline: str
    reason: str
    scores: scoring.RepoScores
    labels: taxonomy.RepoLabels | None  # None = chưa phân loại


@dataclass(frozen=True, slots=True)
class UnverifiedRow:
    """Ứng viên chưa xác minh: số tăng chỉ là ước lượng, điểm Tiềm năng cũng ghi "(ước lượng)"."""

    check: RisingCheck
    potential: Score


@dataclass(frozen=True, slots=True)
class DailyReport:
    run: DailyRun
    rising: list[RisingRow]
    # Dòng qua bộ lọc nhưng "Nghi cao" star giả: ẩn khỏi bảng chính, có nút hiện (kèm lý do).
    hidden: list[RisingRow]
    unverified: list[UnverifiedRow]
    scans: list[DailyRunScan]
    # Số dòng đã xác minh bằng lịch sử chính thức, bất kể ngưỡng lọc của người xem.
    verified_count: int
    # Số rising star của lượt (ngưỡng mặc định, như `run.rising_count`) bị ẩn vì "Nghi cao".
    hidden_rising_count: int


def daily_report(
    run: DailyRun,
    *,
    max_stars: int = growth.RISING_MAX_STARS,
    min_gain: int = growth.RISING_MIN_GAIN_7D,
    sort: str = SORT_POTENTIAL,
    audience: Sequence[str] = (),
    aspects: Sequence[str] = (),
) -> DailyReport:
    """Báo cáo của một lượt, lọc theo ngưỡng người dùng chọn. Chỉ đọc dữ liệu đã lưu, không gọi API.

    - Bảng rising: dòng đã xác minh bằng lịch sử chính thức, dưới `max_stars` star và tăng từ
      `min_gain` trong 7 ngày; sắp theo điểm Tiềm năng (hoà thì tăng nhiều trước), hoặc theo số
      tăng 7 ngày khi `sort="gain"`.
    - Dòng "Nghi cao" star giả (sau bộ lọc) nằm ở `hidden`, không ở bảng chính.
    - "Mới vào danh sách": repo không là rising star trong báo cáo liền trước.
    - Mục chưa xác minh: dòng còn là ước lượng (hết ngân sách xác minh, hoặc GitHub trả lỗi).
    - Điểm tính lúc xem (không lưu), từ số liệu repo và hồ sơ chủ đang có trong kho.
    - `audience` / `aspects` (F-010): chỉ giữ repo có ít nhất một nhãn đã chọn ở mỗi lớp được chọn
      (HOẶC trong một lớp, VÀ giữa hai lớp) — như trang Kho repo.
    """
    checks = RisingCheck.objects.filter(daily_run=run).select_related("repository")
    all_verified = list(checks.filter(source=RisingCheck.Source.HISTORY).order_by("-gain_7d", "pk"))
    unverified = list(checks.exclude(source=RisingCheck.Source.HISTORY).order_by("-gain_7d", "pk"))
    every = [*all_verified, *unverified]
    scores = scoring.score_repositories(
        [check.repository for check in every],
        growth={check.repository_id: _growth_facts(check) for check in every},
    )
    labels = taxonomy.labels_for(check.repository_id for check in all_verified)
    verified = [
        check
        for check in all_verified
        if check.stars < max_stars
        and check.gain_7d >= min_gain
        and _has_labels(labels.get(check.repository_id), audience=audience, aspects=aspects)
    ]
    # DEBT(D-009): "Mới vào danh sách" so với ngưỡng mặc định của lượt trước, không theo bộ lọc.
    previous = _reported_runs().filter(day__lt=run.day).order_by("-day").first()
    previous_rising: set[int] = set()
    if previous is not None:
        previous_rising = set(
            previous.checks.filter(is_rising=True).values_list("repository_id", flat=True)
        )
    rows = [
        _rising_row(
            check,
            run=run,
            is_new_entry=check.repository_id not in previous_rising,
            max_stars=max_stars,
            min_gain=min_gain,
            scores=scores[check.repository_id],
            labels=labels.get(check.repository_id),
        )
        for check in verified
    ]
    if sort != SORT_GAIN:
        # Sắp ổn định: hoà điểm thì giữ thứ tự tăng nhiều trước đã có.
        rows.sort(key=lambda row: -_potential_total(row.scores))
    hidden_rising = sum(
        1
        for check in all_verified
        if check.is_rising and scores[check.repository_id].suspicion.is_hidden
    )
    return DailyReport(
        run=run,
        rising=[row for row in rows if not row.scores.suspicion.is_hidden],
        hidden=[row for row in rows if row.scores.suspicion.is_hidden],
        unverified=[
            UnverifiedRow(check, _estimated_potential(scores[check.repository_id]))
            for check in unverified
        ],
        scans=list(run.scans.select_related("scan_run", "watch_query").order_by("position", "pk")),
        verified_count=len(all_verified),
        hidden_rising_count=hidden_rising,
    )


def latest_gain_subquery() -> Subquery:
    """Biểu thức cho `annotate`: star tăng 7 ngày (lịch sử chính thức) ở lần xét gần nhất của repo.

    Repo chưa từng được xác minh thì trống.
    """
    return Subquery(
        RisingCheck.objects.filter(repository=OuterRef("pk"), source=RisingCheck.Source.HISTORY)
        .order_by("-daily_run__day", "-pk")
        .values("gain_7d")[:1]
    )


def latest_rising_repository_ids() -> QuerySet[RisingCheck, int]:
    """Truy vấn con: id repo là rising star ở báo cáo mới nhất (rỗng khi chưa có báo cáo)."""
    run = latest_report_run()
    if run is None:
        return RisingCheck.objects.none().values_list("repository_id", flat=True)
    return RisingCheck.objects.filter(daily_run=run, is_rising=True).values_list(
        "repository_id", flat=True
    )


def latest_report_run() -> DailyRun | None:
    """Lượt mới nhất đã lập xong báo cáo (trang Rising star mở báo cáo này mặc định)."""
    return _reported_runs().order_by("-day").first()


def report_run_for(day: date) -> DailyRun | None:
    """Lượt đã lập xong báo cáo của ngày `day` (giờ Việt Nam); chưa có thì None."""
    return _reported_runs().filter(day=day).first()


def report_days() -> list[date]:
    """Các ngày có báo cáo, mới trước — để chọn xem báo cáo ngày khác."""
    return list(_reported_runs().order_by("-day").values_list("day", flat=True))


def _reported_runs() -> QuerySet[DailyRun]:
    """Lượt đã xong ở bước lập báo cáo. Lượt bị đóng khi hết ngày ở bước trước thì không tính."""
    return DailyRun.objects.filter(
        step=DailyRun.Step.REPORT,
        status__in=[DailyRun.Status.SUCCEEDED, DailyRun.Status.SUCCEEDED_PARTIAL],
    )


def _has_labels(
    labels: taxonomy.RepoLabels | None, *, audience: Sequence[str], aspects: Sequence[str]
) -> bool:
    if not audience and not aspects:
        return True
    if labels is None:
        return False
    audience_ok = not audience or any(c.code in audience for c in labels.audience)
    aspects_ok = not aspects or any(c.code in aspects for c in labels.aspects)
    return audience_ok and aspects_ok


def _growth_facts(check: RisingCheck) -> GrowthFacts:
    """Số tăng của dòng xét để chấm Tiềm năng và tín hiệu "dồn một ngày"."""
    verified = check.source == RisingCheck.Source.HISTORY
    return GrowthFacts(
        stars=check.stars,
        gain_7d=check.gain_7d,
        gain_30d=check.gain_30d if verified else None,
        series=tuple(check.series) if verified else (),
        estimated=not verified,
    )


def _potential_total(scores: scoring.RepoScores) -> int:
    return scores.potential.total if scores.potential is not None else 0


def _estimated_potential(scores: scoring.RepoScores) -> Score:
    if scores.potential is None:
        raise ValueError("Dòng chưa xác minh phải có điểm Tiềm năng (đã truyền số tăng ước lượng)")
    return scores.potential


def _rising_row(
    check: RisingCheck,
    *,
    run: DailyRun,
    is_new_entry: bool,
    max_stars: int,
    min_gain: int,
    scores: scoring.RepoScores,
    labels: taxonomy.RepoLabels | None,
) -> RisingRow:
    repository = check.repository
    # Tuổi tính tới ngày của lượt (không phải hôm nay): xem lại báo cáo cũ vẫn khớp cờ
    # "Repo rất mới".
    age_days = (run.day - timezone.localdate(repository.gh_created_at)).days
    return RisingRow(
        check=check,
        repository=repository,
        is_new_entry=is_new_entry,
        growth_percent=growth.growth_percent_7d(check.stars, check.gain_7d),
        age_days=age_days,
        flag_labels=tuple(growth.FLAG_LABELS[growth.Flag(flag)] for flag in check.flags),
        sparkline=growth.sparkline_points(check.series),
        reason=_reason(check, max_stars=max_stars, min_gain=min_gain),
        scores=scores,
        labels=labels,
    )


def _reason(check: RisingCheck, *, max_stars: int, min_gain: int) -> str:
    """Dòng "Vì sao có mặt" (thiết kế mục 4): con số, ngưỡng, nguồn và khoảng ngày UTC đã dùng."""
    window_end = check.window_end
    if window_end is None:
        raise ValueError(f"Dòng xét #{check.pk} đã xác minh mà thiếu ngày UTC cuối của cửa sổ")
    window_start = window_end - timedelta(days=growth.WINDOW_DAYS - 1)
    return (
        f"+{_number(check.gain_7d)} star trong 7 ngày (ngưỡng {_number(min_gain)}) · "
        f"đang {_number(check.stars)} star (dưới {_number(max_stars)}) · "
        # Gạch nối khoảng ngày giữ đúng mẫu ở mục 4 của thiết kế.
        f"nguồn: lịch sử star GitHub, ngày UTC {window_start:%d/%m}–{window_end:%d/%m}"  # noqa: RUF001
    )


def _number(value: int) -> str:
    """Số kiểu Việt Nam, có dấu ngăn nghìn "." (1.000) — cùng cách bộ lọc `intcomma` ở trang web."""
    return formats.number_format(value, force_grouping=True)


# --- Trạng thái hôm nay, danh sách theo dõi, ước lượng, lịch sử --------------------------------

HEADLINE_NO_RUN_EARLY = "Hôm nay chưa chạy — sẽ chạy sau 7:00."
HEADLINE_NO_RUN_LATE = (
    "Hôm nay chưa chạy — app sẽ tự chạy ở nhịp kiểm tra sau (miễn là app đang mở), "
    "hoặc bấm Chạy ngay."
)
HEADLINE_STALE = (
    "Bị gián đoạn — lượt không còn nhịp sống. App tự chạy tiếp ở nhịp sau, hoặc bấm Chạy tiếp."
)
RECENT_RUNS_SHOWN = 14


@dataclass(frozen=True, slots=True)
class TodayStatus:
    """Lượt hôm nay cho đầu trang: câu mô tả và các nút được hiện (Chạy ngay / Chạy tiếp / Dừng)."""

    run: DailyRun | None
    headline: str
    is_live: bool
    can_stop: bool
    can_run_now: bool

    @property
    def run_now_label(self) -> str:
        """Tên nút chạy: "Chạy ngay" khi hôm nay chưa có lượt, "Chạy tiếp" khi đã có lượt dở."""
        return "Chạy ngay" if self.run is None else "Chạy tiếp"


@dataclass(frozen=True, slots=True)
class WatchRow:
    """Một truy vấn theo dõi kèm lần quét gần nhất của nó (trong lượt hằng ngày nào)."""

    watch: WatchQuery
    last_scan: ScanRun | None
    last_day: date | None


@dataclass(frozen=True, slots=True)
class DailyEstimate:
    """Ước lượng một ngày chạy tốn bao nhiêu lượt gọi và thời gian; `None` khi chưa có lượt nào."""

    calls: int | None
    minutes: int | None
    based_on_day: date | None
    has_token: bool
    seconds_per_call: float


def today_status(*, now: datetime | None = None) -> TodayStatus:
    """Trạng thái lượt hôm nay (giờ Việt Nam) và các nút được hiện.

    - "Dừng" chỉ khi lượt đang chạy thật; nút chạy ("Chạy ngay" khi chưa có lượt, "Chạy tiếp" khi
      lượt đang Tạm dừng / Lỗi / bị gián đoạn). Lượt đã Xong thì không nút nào: mỗi ngày một lượt.
    - `now` quyết định ngày nào là "hôm nay"; nhịp sống luôn so với giờ thật.
    """
    moment = now if now is not None else timezone.now()
    run = DailyRun.objects.filter(day=timezone.localdate(moment)).first()
    if run is None:
        late = timezone.localtime(moment).time() >= DAILY_RUN_AFTER
        headline = HEADLINE_NO_RUN_LATE if late else HEADLINE_NO_RUN_EARLY
        return TodayStatus(run, headline, is_live=False, can_stop=False, can_run_now=True)
    is_live = _is_live(run, timezone.now() - discovery.LIVE_HEARTBEAT_WINDOW)
    can_run_now = run.status in (DailyRun.Status.PAUSED, DailyRun.Status.FAILED) or (
        run.status == DailyRun.Status.RUNNING and not is_live
    )
    return TodayStatus(
        run,
        _headline(run, is_live=is_live),
        is_live=is_live,
        can_stop=is_live,
        can_run_now=can_run_now,
    )


def watch_overview() -> list[WatchRow]:
    """Danh sách theo dõi (theo thứ tự), mỗi truy vấn kèm lần quét gần nhất của nó."""
    newest_link = (
        DailyRunScan.objects.filter(watch_query=OuterRef("pk"))
        .order_by("-daily_run__day", "-position")
        .values("pk")[:1]
    )
    watches = list(WatchQuery.objects.annotate(newest_link_id=Subquery(newest_link)))
    links = DailyRunScan.objects.select_related("scan_run", "daily_run").in_bulk(
        [watch.newest_link_id for watch in watches if watch.newest_link_id is not None]
    )
    rows: list[WatchRow] = []
    for watch in watches:
        if watch.newest_link_id is None:
            rows.append(WatchRow(watch, None, None))
        else:
            link = links[watch.newest_link_id]
            rows.append(WatchRow(watch, link.scan_run, link.daily_run.day))
    return rows


def next_watch_position() -> int:
    """Thứ tự gợi ý cho truy vấn mới: ngay sau truy vấn cuối."""
    return (WatchQuery.objects.aggregate(top=Max("position"))["top"] or 0) + 1


def daily_estimate() -> DailyEstimate:
    """Ước lượng lượt gọi và thời gian một ngày chạy, theo lượt gần nhất đã lập báo cáo.

    Thời gian = số lượt gọi nhân nhịp giãn của GitHub (2,1 giây có token, 6,1 giây không token).
    Lượt dở, lỗi hay bị đóng giữa chừng không đại diện cho một ngày chạy trọn nên không tính.
    """
    has_token = bool(settings.GITHUB_TOKEN)
    seconds = MIN_INTERVAL_WITH_TOKEN if has_token else MIN_INTERVAL_ANONYMOUS
    latest = _reported_runs().order_by("-day").first()
    if latest is None:
        return DailyEstimate(None, None, None, has_token, seconds)
    calls = (
        latest.search_calls_used
        + latest.verify_calls_used
        + latest.owner_calls_used
        + latest.ai_calls_used
    )
    # Làm tròn giây trước khi chia: 800 lượt nhân 2,1 giây ra 1680,0000000000002 trong số thực.
    minutes = math.ceil(round(calls * seconds) / 60)
    return DailyEstimate(calls, minutes, latest.day, has_token, seconds)


def recent_daily_runs(limit: int = RECENT_RUNS_SHOWN) -> QuerySet[DailyRun]:
    """Các lượt hằng ngày gần nhất, mới trước."""
    return DailyRun.objects.all()[:limit]


def _headline(run: DailyRun, *, is_live: bool) -> str:
    if run.status == DailyRun.Status.RUNNING:
        return _running_headline(run) if is_live else HEADLINE_STALE
    if run.status == DailyRun.Status.PAUSED:
        return f"Tạm dừng ở bước «{run.get_step_display()}»: {run.stop_reason}"
    if run.status == DailyRun.Status.FAILED:
        return f"Lỗi: {run.error_message}"
    at = f" lúc {timezone.localtime(run.finished_at):%H:%M}" if run.finished_at else ""
    label = "Xong" if run.status == DailyRun.Status.SUCCEEDED else "Xong nhưng còn sót"
    return f"{label}{at} — {run.rising_count} rising star."


def _running_headline(run: DailyRun) -> str:
    if run.step == DailyRun.Step.RESCAN:
        done, total, current = _rescan_progress(run)
        target = f"«{current}»" if current else "danh sách theo dõi"
        return f"Đang chạy: quét lại {target} — đã xong {done}/{total} truy vấn."
    if run.step == DailyRun.Step.SCREEN:
        return "Đang chạy: lọc thô bằng ảnh chụp star."
    if run.step == DailyRun.Step.VERIFY:
        used = (
            f" — đã dùng {run.verify_calls_used}/{run.verify_budget} lượt gọi"
            if run.verify_budget
            else ""
        )
        return f"Đang chạy: xác minh ứng viên bằng lịch sử star{used}."
    if run.step == DailyRun.Step.OWNERS:
        used = (
            f" — đã dùng {run.owner_calls_used}/{run.owner_budget} lượt gọi"
            if run.owner_budget
            else ""
        )
        return f"Đang chạy: lấy hồ sơ chủ repo của rising star{used}."
    if run.step == DailyRun.Step.CLASSIFY:
        used = f" — đã dùng {run.ai_calls_used} lượt gọi" if run.ai_calls_used else ""
        return f"Đang chạy: phân loại repo của lượt bằng AI{used}."
    return "Đang chạy: lập báo cáo và dọn dữ liệu cũ."


def _rescan_progress(run: DailyRun) -> tuple[int, int, str | None]:
    """(số truy vấn đã quét xong, số truy vấn đang bật, truy vấn đang quét nếu có).

    Không dùng `position` làm tiến độ: nó đếm cả lần quét lại sau lỗi token. Lần quét lỗi token /
    lỗi code sẽ được thay bằng lần mới nên chưa tính là xong.
    """
    enabled = set(WatchQuery.objects.filter(enabled=True).values_list("pk", flat=True))
    links = list(run.scans.select_related("scan_run"))
    finished = {
        link.watch_query_id
        for link in links
        if link.watch_query_id in enabled
        and link.scan_run.status in _SCAN_FINISHED
        and not _needs_new_scan(link.scan_run)
    }
    running = [
        link.scan_run.query for link in links if link.scan_run.status == ScanRun.Status.RUNNING
    ]
    return len(finished), len(enabled), running[-1] if running else None
