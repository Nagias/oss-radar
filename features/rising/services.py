"""Nghiệp vụ của Rising star: lượt quét hằng ngày theo danh sách theo dõi.

Mỗi ngày (giờ Việt Nam) có tối đa một lượt, gồm 7 bước: quét lại danh sách theo dõi → lọc thô →
xác minh rising → xác minh trending (F-011) → lấy hồ sơ chủ của rising star (F-006) → phân loại
repo của lượt bằng AI (F-010) → lập báo cáo. Việc định kỳ `classify_backlog_if_due` phân loại dần
phần còn lại của kho. Bước đang làm lưu trong CSDL: bị gián đoạn thì lần sau làm tiếp từ bước dở.
Lượt tự bắt đầu sau 7:00 (`run_daily_if_due`, việc định kỳ của bộ nhịp), hoặc khi bấm "Chạy ngay" /
lệnh `daily` (`prepare_daily_run` rồi `execute_daily_run`).

Hàm đọc cho trang web: báo cáo (`daily_report`, `latest_report_run`…), trạng thái hôm nay
(`today_status`), danh sách theo dõi (`watch_overview`), ước lượng lượt gọi mỗi ngày
(`daily_estimate`) và lịch sử các lượt (`recent_daily_runs`).

Đây là cửa công khai duy nhất (QĐ-21): code nằm ở các module con `_common`, `_runner`,
`daily_run`, `report`, `overview`; tính năng khác, view và lệnh chỉ import `services`.
"""

from features.rising._common import (
    BACKLOG_CALLS_PER_TICK as BACKLOG_CALLS_PER_TICK,
)
from features.rising._common import (
    BACKLOG_PAUSE_AFTER_ERROR as BACKLOG_PAUSE_AFTER_ERROR,
)
from features.rising._common import (
    CLASSIFY_BLOCKED_NOTE as CLASSIFY_BLOCKED_NOTE,
)
from features.rising._common import (
    DAILY_RUN_AFTER as DAILY_RUN_AFTER,
)
from features.rising._common import (
    DAILY_RUN_CLASSIFY_CALLS as DAILY_RUN_CLASSIFY_CALLS,
)
from features.rising._common import (
    EMPTY_WATCH_LIST_NOTE as EMPTY_WATCH_LIST_NOTE,
)
from features.rising._common import (
    MAX_AUTO_CONTINUES as MAX_AUTO_CONTINUES,
)
from features.rising._common import (
    OWNER_BUDGET_ANONYMOUS as OWNER_BUDGET_ANONYMOUS,
)
from features.rising._common import (
    OWNER_BUDGET_NOTE as OWNER_BUDGET_NOTE,
)
from features.rising._common import (
    OWNER_BUDGET_WITH_TOKEN as OWNER_BUDGET_WITH_TOKEN,
)
from features.rising._common import (
    OWNERS_BLOCKED_NOTE as OWNERS_BLOCKED_NOTE,
)
from features.rising._common import (
    REASON_BLOCKED as REASON_BLOCKED,
)
from features.rising._common import (
    REASON_BUSY as REASON_BUSY,
)
from features.rising._common import (
    REASON_BUSY_APP as REASON_BUSY_APP,
)
from features.rising._common import (
    REASON_CTRL_C as REASON_CTRL_C,
)
from features.rising._common import (
    REASON_INTERRUPTED as REASON_INTERRUPTED,
)
from features.rising._common import (
    REASON_STOPPED as REASON_STOPPED,
)
from features.rising._common import (
    REASON_VERIFY_AUTH as REASON_VERIFY_AUTH,
)
from features.rising._common import (
    REASON_VERIFY_BLOCKED as REASON_VERIFY_BLOCKED,
)
from features.rising._common import (
    RETRY_LATER_AFTER as RETRY_LATER_AFTER,
)
from features.rising._common import (
    TRENDING_BLOCKED_NOTE as TRENDING_BLOCKED_NOTE,
)
from features.rising._common import (
    TRENDING_BUDGET_ANONYMOUS as TRENDING_BUDGET_ANONYMOUS,
)
from features.rising._common import (
    TRENDING_BUDGET_NOTE as TRENDING_BUDGET_NOTE,
)
from features.rising._common import (
    TRENDING_BUDGET_WITH_TOKEN as TRENDING_BUDGET_WITH_TOKEN,
)
from features.rising._common import (
    TRENDING_SKIPPED_NOTE as TRENDING_SKIPPED_NOTE,
)
from features.rising._common import (
    UNREADABLE_HISTORY_NOTE as UNREADABLE_HISTORY_NOTE,
)
from features.rising._common import (
    UNREADABLE_OWNER_NOTE as UNREADABLE_OWNER_NOTE,
)
from features.rising._common import (
    VERIFY_BUDGET_ANONYMOUS as VERIFY_BUDGET_ANONYMOUS,
)
from features.rising._common import (
    VERIFY_BUDGET_NOTE as VERIFY_BUDGET_NOTE,
)
from features.rising._common import (
    VERIFY_BUDGET_WITH_TOKEN as VERIFY_BUDGET_WITH_TOKEN,
)
from features.rising._common import (
    DailyRunBlockedError as DailyRunBlockedError,
)
from features.rising._common import (
    DailySupersededError as DailySupersededError,
)
from features.rising.daily_run import (
    classify_backlog_if_due as classify_backlog_if_due,
)
from features.rising.daily_run import (
    close_previous_days as close_previous_days,
)
from features.rising.daily_run import (
    execute_daily_run as execute_daily_run,
)
from features.rising.daily_run import (
    live_daily_run as live_daily_run,
)
from features.rising.daily_run import (
    pause_stale_daily_runs as pause_stale_daily_runs,
)
from features.rising.daily_run import (
    prepare_daily_run as prepare_daily_run,
)
from features.rising.daily_run import (
    release_unstarted_daily_run as release_unstarted_daily_run,
)
from features.rising.daily_run import (
    request_daily_stop as request_daily_stop,
)
from features.rising.daily_run import (
    run_daily_if_due as run_daily_if_due,
)
from features.rising.overview import (
    HEADLINE_NO_RUN_EARLY as HEADLINE_NO_RUN_EARLY,
)
from features.rising.overview import (
    HEADLINE_NO_RUN_LATE as HEADLINE_NO_RUN_LATE,
)
from features.rising.overview import (
    HEADLINE_STALE as HEADLINE_STALE,
)
from features.rising.overview import (
    RECENT_RUNS_SHOWN as RECENT_RUNS_SHOWN,
)
from features.rising.overview import (
    DailyEstimate as DailyEstimate,
)
from features.rising.overview import (
    TodayStatus as TodayStatus,
)
from features.rising.overview import (
    WatchRow as WatchRow,
)
from features.rising.overview import (
    daily_estimate as daily_estimate,
)
from features.rising.overview import (
    next_watch_position as next_watch_position,
)
from features.rising.overview import (
    recent_daily_runs as recent_daily_runs,
)
from features.rising.overview import (
    today_status as today_status,
)
from features.rising.overview import (
    watch_overview as watch_overview,
)
from features.rising.report import (
    RISING_PAGE_SIZE as RISING_PAGE_SIZE,
)
from features.rising.report import (
    SORT_GAIN as SORT_GAIN,
)
from features.rising.report import (
    SORT_POTENTIAL as SORT_POTENTIAL,
)
from features.rising.report import (
    UNVERIFIED_PAGE_SIZE as UNVERIFIED_PAGE_SIZE,
)
from features.rising.report import (
    DailyReport as DailyReport,
)
from features.rising.report import (
    PageInfo as PageInfo,
)
from features.rising.report import (
    RisingRow as RisingRow,
)
from features.rising.report import (
    UnverifiedRow as UnverifiedRow,
)
from features.rising.report import (
    daily_report as daily_report,
)
from features.rising.report import (
    latest_gain_subquery as latest_gain_subquery,
)
from features.rising.report import (
    latest_report_run as latest_report_run,
)
from features.rising.report import (
    latest_rising_repository_ids as latest_rising_repository_ids,
)
from features.rising.report import (
    latest_trending_repository_ids as latest_trending_repository_ids,
)
from features.rising.report import (
    report_days as report_days,
)
from features.rising.report import (
    report_run_for as report_run_for,
)
