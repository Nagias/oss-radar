"""Số liệu cho trang Theo dõi và đầu trang Rising star: trạng thái hôm nay, danh sách theo dõi,
ước lượng lượt gọi mỗi ngày, lịch sử các lượt."""

from datetime import date, timedelta

import pytest
from django.utils import timezone
from pytest_django.fixtures import DjangoAssertNumQueries, Settings

from features.discovery.models import ScanRun
from features.rising import services
from features.rising.models import DailyRun, DailyRunScan, WatchQuery
from features.rising.tests.conftest import WATCHED, at, make_run

pytestmark = pytest.mark.django_db

Status = DailyRun.Status
Step = DailyRun.Step
A, B, C = WATCHED


def today_run(**fields: object) -> DailyRun:
    """Lượt của hôm nay; mặc định đang chạy thật (nhịp sống vừa ghi) ở bước quét lại."""
    defaults: dict[str, object] = {
        "status": Status.RUNNING,
        "step": Step.RESCAN,
        "heartbeat_at": timezone.now(),
    }
    return DailyRun.objects.create(day=timezone.localdate(), **{**defaults, **fields})


def link_scan(
    run: DailyRun, watch: WatchQuery, *, status: str, position: int, **fields: object
) -> ScanRun:
    scan = ScanRun.objects.create(
        query=watch.query, origin=ScanRun.Origin.DAILY, status=status, **fields
    )
    DailyRunScan.objects.create(daily_run=run, watch_query=watch, scan_run=scan, position=position)
    return scan


# --- Trạng thái hôm nay ----------------------------------------------------------------------


def test_status_before_first_run_depends_on_the_hour() -> None:
    early = services.today_status(now=at(6, 30))
    late = services.today_status(now=at(9, 0))

    assert early.run is None
    assert early.headline == "Hôm nay chưa chạy — sẽ chạy sau 7:00."
    assert "tự chạy" in late.headline
    for status in (early, late):
        assert (status.is_live, status.can_stop, status.can_run_now) == (False, False, True)


def test_status_of_live_run_names_the_query_in_progress(watch_list: list[WatchQuery]) -> None:
    run = today_run()
    link_scan(run, watch_list[0], status=ScanRun.Status.SUCCEEDED, position=1)
    link_scan(run, watch_list[1], status=ScanRun.Status.RUNNING, position=2)

    status = services.today_status()

    assert status.run == run
    assert status.headline == f"Đang chạy: quét lại «{B}» — đã xong 1/3 truy vấn."
    assert (status.is_live, status.can_stop, status.can_run_now) == (True, True, False)


def test_status_progress_ignores_scans_that_will_be_redone(watch_list: list[WatchQuery]) -> None:
    run = today_run()
    link_scan(run, watch_list[0], status=ScanRun.Status.SUCCEEDED, position=1)
    # Lần quét lỗi token / lỗi code được thay bằng lần mới, nên chưa tính là xong.
    link_scan(
        run,
        watch_list[1],
        status=ScanRun.Status.FAILED,
        position=2,
        error_kind=ScanRun.ErrorKind.AUTH,
    )
    # Truy vấn sai cú pháp thì không tự khỏi: coi là xong.
    link_scan(
        run,
        watch_list[2],
        status=ScanRun.Status.FAILED,
        position=3,
        error_kind=ScanRun.ErrorKind.QUERY,
    )

    status = services.today_status()

    assert status.headline == "Đang chạy: quét lại danh sách theo dõi — đã xong 2/3 truy vấn."


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (Step.SCREEN, "Đang chạy: lọc thô bằng ảnh chụp star."),
        (
            Step.VERIFY,
            "Đang chạy: xác minh ứng viên bằng lịch sử star — đã dùng 5/300 lượt gọi.",
        ),
        (Step.REPORT, "Đang chạy: lập báo cáo và dọn dữ liệu cũ."),
    ],
)
def test_status_of_live_run_in_later_steps(step: int, expected: str) -> None:
    today_run(step=step, verify_budget=300, verify_calls_used=5)

    assert services.today_status().headline == expected


def test_status_run_with_stale_heartbeat_counts_as_interrupted() -> None:
    today_run(heartbeat_at=timezone.now() - timedelta(minutes=10))

    status = services.today_status()

    assert "Bị gián đoạn" in status.headline
    assert (status.is_live, status.can_stop, status.can_run_now) == (False, False, True)


def test_status_of_paused_and_failed_run_offers_run_now() -> None:
    paused = today_run(
        status=Status.PAUSED, step=Step.VERIFY, stop_reason="GitHub đang chặn.", heartbeat_at=None
    )

    status = services.today_status()

    assert status.headline == "Tạm dừng ở bước «Xác minh»: GitHub đang chặn."
    assert (status.is_live, status.can_stop, status.can_run_now) == (False, False, True)

    DailyRun.objects.filter(pk=paused.pk).update(status=Status.FAILED, error_message="Token sai.")

    status = services.today_status()

    assert status.headline == "Lỗi: Token sai."
    assert (status.can_stop, status.can_run_now) == (False, True)


def test_status_of_finished_run_offers_neither_button() -> None:
    run = today_run(
        status=Status.SUCCEEDED,
        step=Step.REPORT,
        heartbeat_at=None,
        finished_at=at(7, 31),
        rising_count=14,
    )

    done = services.today_status()

    assert done.headline == "Xong lúc 07:31 — 14 rising star."
    assert (done.is_live, done.can_stop, done.can_run_now) == (False, False, False)

    DailyRun.objects.filter(pk=run.pk).update(status=Status.SUCCEEDED_PARTIAL)

    partial = services.today_status()

    assert partial.headline == "Xong nhưng còn sót lúc 07:31 — 14 rising star."
    assert (partial.can_stop, partial.can_run_now) == (False, False)


def test_run_now_label_says_continue_only_when_todays_run_exists() -> None:
    assert services.today_status(now=at(9, 0)).run_now_label == "Chạy ngay"

    run = today_run(status=Status.PAUSED, heartbeat_at=None)
    assert services.today_status().run_now_label == "Chạy tiếp"

    DailyRun.objects.filter(pk=run.pk).update(status=Status.FAILED)
    assert services.today_status().run_now_label == "Chạy tiếp"

    # Lượt "đang chạy" nhưng nhịp sống đã cũ (trang chưa kịp đánh dấu Tạm dừng): cũng là chạy tiếp.
    DailyRun.objects.filter(pk=run.pk).update(
        status=Status.RUNNING, heartbeat_at=timezone.now() - timedelta(minutes=10)
    )
    stale = services.today_status()
    assert (stale.can_run_now, stale.run_now_label) == (True, "Chạy tiếp")


def test_busy_and_stale_texts_name_the_continue_button() -> None:
    assert "Chạy tiếp" in services.REASON_BUSY_APP
    assert "Chạy tiếp" in services.HEADLINE_STALE
    assert "Chạy ngay" not in services.REASON_BUSY_APP + services.HEADLINE_STALE
    assert "Chạy ngay" in services.HEADLINE_NO_RUN_LATE  # chưa có lượt: nút là Chạy ngay


def test_status_ignores_other_days() -> None:
    make_run(timezone.localdate() - timedelta(days=1))

    assert services.today_status().run is None


# --- Danh sách theo dõi ----------------------------------------------------------------------


def test_watch_overview_pairs_each_query_with_its_latest_scan(
    watch_list: list[WatchQuery], django_assert_max_num_queries: DjangoAssertNumQueries
) -> None:
    today = timezone.localdate()
    old_run = make_run(today - timedelta(days=1))
    run = today_run(status=Status.SUCCEEDED, step=Step.REPORT)
    link_scan(old_run, watch_list[0], status=ScanRun.Status.SUCCEEDED, position=1, fetched_count=1)
    # Truy vấn A quét lại hai lần trong lượt hôm nay (lần đầu lỗi token): lấy lần sau cùng.
    link_scan(run, watch_list[0], status=ScanRun.Status.FAILED, position=1)
    last = link_scan(
        run, watch_list[0], status=ScanRun.Status.SUCCEEDED, position=3, fetched_count=250
    )
    link_scan(old_run, watch_list[1], status=ScanRun.Status.SUCCEEDED, position=2, fetched_count=7)

    with django_assert_max_num_queries(2):  # không tốn một truy vấn cho mỗi truy vấn theo dõi
        rows = services.watch_overview()

    assert [row.watch for row in rows] == watch_list
    assert (rows[0].last_scan, rows[0].last_day) == (last, today)
    assert rows[1].last_scan is not None
    assert (rows[1].last_scan.fetched_count, rows[1].last_day) == (7, today - timedelta(days=1))
    assert (rows[2].last_scan, rows[2].last_day) == (None, None)


def test_next_watch_position_goes_after_the_last(watch_list: list[WatchQuery]) -> None:
    assert services.next_watch_position() == len(watch_list) + 1

    WatchQuery.objects.all().delete()

    assert services.next_watch_position() == 1


# --- Ước lượng, lịch sử ----------------------------------------------------------------------


def test_estimate_before_any_run_has_no_numbers() -> None:
    estimate = services.daily_estimate()

    assert (estimate.calls, estimate.minutes, estimate.based_on_day) == (None, None, None)


def test_estimate_follows_latest_reported_run_and_token(settings: Settings) -> None:
    today = timezone.localdate()
    older = make_run(today - timedelta(days=2))
    DailyRun.objects.filter(pk=older.pk).update(search_calls_used=10, verify_calls_used=10)
    newest = make_run(today - timedelta(days=1))
    DailyRun.objects.filter(pk=newest.pk).update(search_calls_used=500, verify_calls_used=300)
    # Lượt dở hay lượt lỗi hôm nay không đại diện cho một ngày chạy trọn.
    today_run(search_calls_used=3000, verify_calls_used=0)

    settings.GITHUB_TOKEN = "test-token"
    with_token = services.daily_estimate()

    assert (with_token.calls, with_token.based_on_day) == (800, today - timedelta(days=1))
    assert (with_token.has_token, with_token.seconds_per_call) == (True, 2.1)
    assert with_token.minutes == 28  # 800 lượt nhân 2,1 giây = 28 phút

    settings.GITHUB_TOKEN = ""
    anonymous = services.daily_estimate()

    assert (anonymous.has_token, anonymous.seconds_per_call) == (False, 6.1)
    assert anonymous.minutes == 82  # 800 lượt nhân 6,1 giây = 81,3 phút, làm tròn lên


def test_estimate_of_a_run_with_no_calls_is_zero_minutes() -> None:
    make_run(timezone.localdate() - timedelta(days=1))

    estimate = services.daily_estimate()

    assert (estimate.calls, estimate.minutes) == (0, 0)


def test_recent_daily_runs_are_newest_first_and_limited() -> None:
    days = [date(2026, 10, 20) + timedelta(days=offset) for offset in range(4)]
    for day in days:
        make_run(day)

    recent = services.recent_daily_runs(limit=3)

    assert [run.day for run in recent] == [days[3], days[2], days[1]]
