"""Lịch của lượt hằng ngày (đồng hồ giả qua `now=`): sau 7:00, không chạy lại ngày đã xong, chờ lần
quét khác, tự chạy tiếp có giới hạn, sang ngày mới thì đóng lượt cũ."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

from features.discovery import services as discovery
from features.discovery.models import ScanRun
from features.rising import services
from features.rising.models import DailyRun, DailyRunScan, WatchQuery
from features.rising.tests.conftest import (
    AppKilledError,
    UseFake,
    at,
    make_heartbeats_stale,
    some_repos,
)

pytestmark = pytest.mark.django_db

Status = DailyRun.Status
PauseKind = DailyRun.PauseKind


def test_not_due_before_7am_then_runs_at_first_tick_after(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())

    assert services.run_daily_if_due(now=at(6, 59)) is None
    assert not DailyRun.objects.exists()
    assert fake.search.queries == []

    run = services.run_daily_if_due(now=at(7, 5))  # nhịp đầu tiên sau 7:00, app vẫn mở từ 6:59

    assert run is not None
    assert (run.day, run.status) == (timezone.localdate(), Status.SUCCEEDED)
    assert run.started_at == at(7, 5)
    assert run.scans.count() == 3


def test_not_rerun_when_today_succeeded(watch_list: list[WatchQuery], use_fake: UseFake) -> None:
    fake = use_fake(some_repos())
    DailyRun.objects.create(day=timezone.localdate(), status=Status.SUCCEEDED)

    assert services.run_daily_if_due(now=at(9)) is None
    assert DailyRun.objects.count() == 1
    assert fake.search.queries == []


def test_waits_while_manual_scan_live(watch_list: list[WatchQuery], use_fake: UseFake) -> None:
    fake = use_fake(some_repos())
    discovery.start_scan(discovery.ScanRequest("topic:llm", 0, None, None, None, budget=1))

    assert services.run_daily_if_due(now=at(9)) is None
    assert not DailyRun.objects.exists()
    assert fake.search.queries == []


def test_auto_continue_interrupted_run_max_three_times(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())

    def app_crashes(sent: str) -> None:
        raise AppKilledError

    fake.search.on_query = app_crashes
    with pytest.raises(AppKilledError):
        services.run_daily_if_due(now=at(9))  # lượt mới, làm sập app ngay truy vấn đầu

    for attempt in range(1, services.MAX_AUTO_CONTINUES + 1):
        make_heartbeats_stale()
        with pytest.raises(AppKilledError):
            services.run_daily_if_due(now=at(9, attempt))
        assert DailyRun.objects.get().auto_continue_count == attempt

    make_heartbeats_stale()
    assert services.run_daily_if_due(now=at(10)) is None

    run = DailyRun.objects.get()
    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.INTERRUPTED)
    assert run.auto_continue_count == 3
    assert run.last_auto_continue_at == at(9, 3)
    assert len(fake.search.queries) == 1 + 3  # không lặp mãi, không đốt quota


def test_retry_later_waits_fifteen_minutes(watch_list: list[WatchQuery], use_fake: UseFake) -> None:
    fake = use_fake(some_repos())
    paused = DailyRun.objects.create(
        day=timezone.localdate(),
        status=Status.PAUSED,
        pause_kind=PauseKind.RETRY_LATER,
        paused_at=at(10),
        stop_reason="GitHub chặn (giả lập)",
    )

    assert services.run_daily_if_due(now=at(10, 14)) is None
    assert fake.search.queries == []

    run = services.run_daily_if_due(now=at(10, 15))

    assert run is not None
    assert (run.pk, run.status) == (paused.pk, Status.SUCCEEDED)
    assert run.auto_continue_count == 1
    assert run.last_auto_continue_at == at(10, 15)


def test_user_stopped_run_is_not_auto_continued(use_fake: UseFake) -> None:
    fake = use_fake(some_repos())
    run = DailyRun.objects.create(
        day=timezone.localdate(),
        status=Status.PAUSED,
        pause_kind=PauseKind.STOPPED,
        paused_at=at(8),
    )

    assert services.run_daily_if_due(now=at(10)) is None

    run.refresh_from_db()
    assert (run.status, run.auto_continue_count) == (Status.PAUSED, 0)
    assert fake.search.queries == []


def test_stop_on_paused_run_cancels_auto_continue(use_fake: UseFake) -> None:
    fake = use_fake(some_repos())
    run = DailyRun.objects.create(
        day=timezone.localdate(),
        status=Status.PAUSED,
        pause_kind=PauseKind.RETRY_LATER,
        paused_at=at(8),
    )

    services.request_daily_stop(run)  # bấm Dừng khi lượt đang chờ GitHub

    run.refresh_from_db()
    assert (run.pause_kind, run.stop_requested) == (PauseKind.STOPPED, True)
    assert services.run_daily_if_due(now=at(10)) is None
    assert fake.search.queries == []


@pytest.mark.parametrize("pressed_on", ["daily_page", "scan_page"])
def test_stop_pressed_just_before_app_closed_is_not_auto_continued(
    watch_list: list[WatchQuery], use_fake: UseFake, pressed_on: str
) -> None:
    fake = use_fake(some_repos())
    run = services.prepare_daily_run()
    child = discovery.start_scan(
        discovery.ScanRequest(
            watch_list[0].query, 10, None, None, None, budget=300, origin=ScanRun.Origin.DAILY
        )
    )
    DailyRunScan.objects.create(
        daily_run=run, watch_query=watch_list[0], scan_run=child, position=1
    )
    if pressed_on == "daily_page":
        services.request_daily_stop(run)
    else:
        discovery.request_stop(child)
    make_heartbeats_stale()  # app tắt trước khi luồng chạy kịp thấy cờ Dừng

    assert services.run_daily_if_due(now=at(10)) is None

    run.refresh_from_db()
    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.STOPPED)
    assert run.auto_continue_count == 0
    assert fake.search.queries == []


def test_child_stopped_just_before_app_closed_is_not_auto_continued(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())
    run = services.prepare_daily_run()
    child = discovery.start_scan(
        discovery.ScanRequest(
            watch_list[0].query, 10, None, None, None, budget=300, origin=ScanRun.Origin.DAILY
        )
    )
    DailyRunScan.objects.create(
        daily_run=run, watch_query=watch_list[0], scan_run=child, position=1
    )
    # Lần quét con đã tự dừng theo nút Dừng (cờ đã được xoá); app tắt trước khi lượt kịp ghi.
    long_ago = timezone.now() - timedelta(minutes=10)
    ScanRun.objects.filter(pk=child.pk).update(
        status=ScanRun.Status.PAUSED,
        stop_reason=discovery.REASON_STOPPED,
        stop_requested=False,
        heartbeat_at=long_ago,
    )
    DailyRun.objects.filter(pk=run.pk).update(heartbeat_at=long_ago)

    assert services.run_daily_if_due(now=at(10)) is None

    run.refresh_from_db()
    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.STOPPED)
    assert fake.search.queries == []


def test_run_now_before_7am_is_allowed() -> None:
    # "Bấm Chạy ngay trước 7:00 vẫn được" (thiết kế mục 5): chỉ lịch tự động mới chờ 7:00.
    run = services.prepare_daily_run(now=at(6))

    assert (run.day, run.status, run.started_at) == (timezone.localdate(), Status.RUNNING, at(6))


def test_previous_day_unfinished_run_is_closed_then_today_runs(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    use_fake(some_repos())
    yesterday = DailyRun.objects.create(
        day=timezone.localdate() - timedelta(days=1),
        status=Status.PAUSED,
        pause_kind=PauseKind.INTERRUPTED,
    )

    run = services.run_daily_if_due(now=at(8))

    yesterday.refresh_from_db()
    assert yesterday.status == Status.SUCCEEDED_PARTIAL
    assert yesterday.stop_reason == "Hết ngày — lượt dừng ở bước «Quét lại danh sách theo dõi»."
    assert yesterday.finished_at is not None
    assert run is not None
    assert (run.day, run.status) == (timezone.localdate(), Status.SUCCEEDED)


def test_previous_day_run_still_live_is_left_to_finish(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())
    yesterday = DailyRun.objects.create(
        day=timezone.localdate() - timedelta(days=1),
        status=Status.RUNNING,
        heartbeat_at=timezone.now(),
    )

    assert services.close_previous_days(timezone.localdate()) == 0
    assert services.run_daily_if_due(now=at(8)) is None

    yesterday.refresh_from_db()
    assert yesterday.status == Status.RUNNING
    assert fake.search.queries == []


def test_relabels_background_job(
    watch_list: list[WatchQuery], use_fake: UseFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake(some_repos())
    labels: list[str] = []
    monkeypatch.setattr("core.background.relabel", labels.append)

    services.run_daily_if_due(now=at(6, 59))
    assert labels == []

    services.run_daily_if_due(now=at(7, 5))

    assert labels == [f"Lượt quét hằng ngày {timezone.localdate():%d/%m}"]


def test_daily_run_is_a_scheduled_job_after_auto_resume() -> None:
    jobs = [import_string(path) for path in settings.SCHEDULED_JOBS]

    assert jobs.index(services.run_daily_if_due) > jobs.index(discovery.resume_interrupted_scan)


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github
