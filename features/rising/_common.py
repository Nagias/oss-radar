"""Hằng số, câu chữ, lớp lỗi và hàm phụ dùng chung giữa các module của lượt hằng ngày."""

import time
from collections.abc import Callable
from datetime import time as clock_time
from datetime import timedelta

from django.conf import settings

from features.discovery import services as discovery
from features.discovery.models import ScanRun
from features.rising.models import RisingCheck
from features.scoring.services import GrowthFacts

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
# muộn; phần còn lại của kho do việc định kỳ phân loại dần, mỗi nhịp tối đa 3 lượt gọi.
DAILY_RUN_CLASSIFY_CALLS = 5
BACKLOG_CALLS_PER_TICK = 3  # ~40 giây mỗi nhịp: không giữ luồng nền lâu (bấm Quét không phải chờ)
BACKLOG_PAUSE_AFTER_ERROR = timedelta(minutes=30)

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


def _needs_new_scan(scan: ScanRun) -> bool:
    return scan.status == ScanRun.Status.FAILED and scan.error_kind in _RESCAN_ERROR_KINDS


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
