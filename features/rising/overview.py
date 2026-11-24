"""Trạng thái hôm nay, danh sách theo dõi, ước lượng lượt gọi mỗi ngày, lịch sử các lượt."""

import math
from dataclasses import dataclass
from datetime import date, datetime

from django.conf import settings
from django.db.models import Max, OuterRef, QuerySet, Subquery
from django.utils import timezone

from features.discovery import services as discovery
from features.discovery.models import ScanRun
from features.rising._common import _SCAN_FINISHED, DAILY_RUN_AFTER, _needs_new_scan
from features.rising.daily_run import _is_live
from features.rising.models import DailyRun, DailyRunScan, WatchQuery
from features.rising.report import _reported_runs
from integrations.github.pacing import (
    MIN_INTERVAL_ANONYMOUS,
    MIN_INTERVAL_WITH_TOKEN,
)

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
