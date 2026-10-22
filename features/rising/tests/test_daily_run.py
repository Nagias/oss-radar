"""Lượt hằng ngày, bước 1: quét lại danh sách theo dõi, xử lý kết quả của từng lần quét con."""

from datetime import timedelta

import pytest
from django.utils import timezone

from features.discovery import services as discovery
from features.discovery.models import ScanRun
from features.rising import services
from features.rising.models import DailyRun, DailyRunScan, WatchQuery
from features.rising.tests.conftest import (
    FROM,
    TO,
    WATCHED,
    AppKilledError,
    UseFake,
    calls_for,
    make_heartbeats_stale,
    some_repos,
)
from tests.fakes import make_search_items

pytestmark = pytest.mark.django_db

A, B, C = WATCHED
Status = DailyRun.Status
PauseKind = DailyRun.PauseKind


def run_daily_now() -> DailyRun:
    """Bấm "Chạy ngay" (hoặc lệnh `daily`): chuẩn bị lượt hôm nay rồi chạy nó tới khi dừng."""
    run = services.prepare_daily_run()
    services.execute_daily_run(run.pk)
    run.refresh_from_db()
    return run


def scan_of(run: DailyRun, query: str) -> ScanRun:
    return run.scans.select_related("scan_run").get(scan_run__query=query).scan_run


def manual_request(query: str = "topic:llm") -> discovery.ScanRequest:
    return discovery.ScanRequest(query, 0, None, None, None, budget=1)


def test_rescan_runs_each_enabled_watch_query_as_daily_scan(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())
    WatchQuery.objects.create(label="Tắt", query="topic:llm", position=2, enabled=False)

    run = run_daily_now()

    assert run.status == Status.SUCCEEDED
    links = list(run.scans.select_related("scan_run", "watch_query").order_by("position"))
    assert [link.scan_run.query for link in links] == list(WATCHED)
    assert [link.watch_query for link in links] == watch_list
    assert [link.position for link in links] == [1, 2, 3]
    for link in links:
        scan = link.scan_run
        assert (scan.origin, scan.status) == (ScanRun.Origin.DAILY, ScanRun.Status.SUCCEEDED)
        assert (scan.min_stars, scan.max_stars, scan.budget) == (10, None, 300)
    assert calls_for(fake, "topic:llm") == 0
    assert run.search_calls_used == 9  # 3 truy vấn, mỗi truy vấn 3 trang
    assert run.new_repo_count == 250  # truy vấn đầu thấy lần đầu; hai truy vấn sau chỉ thấy lại
    assert run.problems == []
    assert (run.runner_token, run.stop_reason) == ("", "")
    assert run.finished_at is not None


def test_query_error_is_recorded_and_next_query_runs(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())
    fake.search.fail_when = lambda sent: 422 if sent.startswith(f"{B} ") else None

    run = run_daily_now()

    assert run.status == Status.SUCCEEDED_PARTIAL
    assert scan_of(run, B).error_kind == ScanRun.ErrorKind.QUERY
    assert scan_of(run, A).status == ScanRun.Status.SUCCEEDED
    assert scan_of(run, C).status == ScanRun.Status.SUCCEEDED
    assert len(run.problems) == 1
    assert B in run.problems[0]
    assert "không chấp nhận truy vấn" in run.problems[0]
    assert run.stop_reason == run.problems[0]


def test_child_scan_out_of_budget_is_noted_and_next_query_runs(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    WatchQuery.objects.filter(query=A).update(budget=1)
    fake = use_fake(some_repos())

    run = run_daily_now()

    assert run.status == Status.SUCCEEDED_PARTIAL
    assert scan_of(run, A).status == ScanRun.Status.SUCCEEDED_PARTIAL
    assert len(run.problems) == 1
    assert A in run.problems[0]
    assert "ngân sách" in run.problems[0]
    assert calls_for(fake, C) == 3


def test_auth_error_fails_whole_run(watch_list: list[WatchQuery], use_fake: UseFake) -> None:
    fake = use_fake(some_repos())
    fake.search.fail_when = lambda sent: 401 if sent.startswith(f"{B} ") else None

    run = run_daily_now()

    assert run.status == Status.FAILED
    assert B in run.error_message
    assert "GITHUB_TOKEN" in run.error_message
    assert calls_for(fake, C) == 0  # truy vấn nào cũng sẽ hỏng như vậy → không gọi thêm
    assert run.scans.count() == 2
    assert run.finished_at is not None
    assert run.runner_token == ""


def test_unexpected_error_marks_failed_and_reraises(
    watch_list: list[WatchQuery], use_fake: UseFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake(some_repos())

    def broken_upsert(*args: object, **kwargs: object) -> None:
        raise RuntimeError("lỗi lập trình giả lập")

    monkeypatch.setattr(discovery, "upsert_repositories", broken_upsert)
    run = services.prepare_daily_run()

    with pytest.raises(RuntimeError, match="giả lập"):
        services.execute_daily_run(run.pk)

    run.refresh_from_db()
    assert run.status == Status.FAILED
    assert "Lỗi không mong đợi" in run.error_message
    assert scan_of(run, A).error_kind == ScanRun.ErrorKind.UNEXPECTED


def test_ctrl_c_pauses_run_as_stopped_and_reraises(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())

    def user_presses_ctrl_c(sent: str) -> None:
        if sent.startswith(f"{B} "):
            raise KeyboardInterrupt

    fake.search.on_query = user_presses_ctrl_c
    run = services.prepare_daily_run()

    with pytest.raises(KeyboardInterrupt):
        services.execute_daily_run(run.pk)

    run.refresh_from_db()
    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.STOPPED)
    assert "Ctrl+C" in run.stop_reason
    assert scan_of(run, B).status == ScanRun.Status.PAUSED


def test_user_stop_on_child_scan_pauses_run_and_continue_resumes_it(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())

    def press_stop_on_scan_page(sent: str) -> None:
        live = discovery.live_scan()
        if sent.startswith(f"{B} ") and live is not None:
            discovery.request_stop(live)

    fake.search.on_query = press_stop_on_scan_page

    run = run_daily_now()

    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.STOPPED)
    assert run.paused_at is not None
    stopped = scan_of(run, B)
    assert (stopped.status, stopped.stop_reason) == (
        ScanRun.Status.PAUSED,
        discovery.REASON_STOPPED,
    )
    assert calls_for(fake, C) == 0

    fake.search.on_query = None
    continued = run_daily_now()  # bấm "Chạy tiếp"

    assert continued.pk == run.pk
    assert continued.status == Status.SUCCEEDED
    assert continued.scans.count() == 3
    resumed = scan_of(continued, B)
    assert resumed.pk == stopped.pk  # nối lại đúng lần quét cũ, không tạo lần mới
    assert (resumed.status, resumed.fetched_count) == (ScanRun.Status.SUCCEEDED, 250)
    assert calls_for(fake, A) == 3  # truy vấn đã xong không bị quét lại


def test_request_daily_stop_also_stops_live_child_scan(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())

    def press_stop_on_daily_page(sent: str) -> None:
        if sent.startswith(f"{B} "):
            services.request_daily_stop(DailyRun.objects.get())

    fake.search.on_query = press_stop_on_daily_page

    run = run_daily_now()

    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.STOPPED)
    assert scan_of(run, B).stop_reason == discovery.REASON_STOPPED
    assert calls_for(fake, B) == 1  # lần quét con dừng ngay trước lượt gọi kế tiếp
    assert calls_for(fake, C) == 0


def test_stop_requested_between_queries_pauses_before_next_query(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())

    def stop_arrives_after_child_saw_its_last_check(sent: str) -> None:
        if sent.startswith(f"{A} ") and calls_for(fake, A) == 3:
            DailyRun.objects.update(stop_requested=True)

    fake.search.on_query = stop_arrives_after_child_saw_its_last_check

    run = run_daily_now()

    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.STOPPED)
    assert scan_of(run, A).status == ScanRun.Status.SUCCEEDED
    assert calls_for(fake, B) == 0
    assert run.search_calls_used == 3


def test_rate_limited_child_scan_pauses_run_for_retry_later(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())
    fake.search.fail_when = lambda sent: 429 if sent.startswith(f"{B} ") else None

    run = run_daily_now()

    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.RETRY_LATER)
    assert scan_of(run, B).stop_reason == discovery.REASON_WAIT_TOO_LONG
    assert run.paused_at is not None
    assert "15 phút" in run.stop_reason
    assert calls_for(fake, C) == 0
    assert run.search_calls_used == 3 + 4  # truy vấn đầu 3 trang; B bị từ chối 4 lần


def test_stop_pressed_while_github_blocks_is_kept_as_user_stop(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())
    fake.search.fail_when = lambda sent: 429 if sent.startswith(f"{B} ") else None

    def press_stop_while_blocked(sent: str) -> None:
        if sent.startswith(f"{B} "):
            DailyRun.objects.update(stop_requested=True)

    fake.search.on_query = press_stop_while_blocked

    run = run_daily_now()

    assert scan_of(run, B).stop_reason == discovery.REASON_WAIT_TOO_LONG
    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.STOPPED)
    assert run.stop_reason == services.REASON_STOPPED  # không tự chạy tiếp ngược ý người dùng


def test_lost_connection_on_child_scan_pauses_run_for_retry_later(use_fake: UseFake) -> None:
    WatchQuery.objects.all().delete()
    WatchQuery.objects.create(label="Thử", query=A, position=1)
    fake = use_fake(make_search_items(2500, start=FROM, end=TO, stars=lambda i: 10 + i))
    # 4 lượt đầu chia lát (mỗi nửa mới vẫn quá 1.000 repo), từ lượt 5 mất mạng: 3 lát lỗi liền nhau.
    fake.search.fail_when = lambda sent: 502 if len(fake.search.queries) > 4 else None

    run = run_daily_now()

    assert scan_of(run, A).stop_reason.startswith("Mất kết nối GitHub liên tục")
    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.RETRY_LATER)


def test_child_scan_paused_elsewhere_pauses_run_as_interrupted(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())

    def paused_by_another_process(sent: str) -> None:
        if sent.startswith(f"{B} "):
            ScanRun.objects.filter(query=B).update(
                status=ScanRun.Status.PAUSED, stop_reason=discovery.REASON_INTERRUPTED
            )

    fake.search.on_query = paused_by_another_process

    run = run_daily_now()

    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.INTERRUPTED)
    assert calls_for(fake, C) == 0

    fake.search.on_query = None
    continued = services.run_daily_if_due()  # nhịp sau tự chạy tiếp

    assert continued is not None
    assert (continued.pk, continued.status) == (run.pk, Status.SUCCEEDED)
    assert continued.auto_continue_count == 1


def test_scan_from_another_window_pauses_run_for_retry_later(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())
    other: list[ScanRun] = []

    def manual_scan_wins_the_race(sent: str) -> None:
        # Lệnh `scan` ở cửa sổ khác giữ chỗ đúng lúc truy vấn đầu vừa xong, lọt qua lần kiểm
        # của nó.
        if sent.startswith(f"{A} ") and calls_for(fake, A) == 3:
            now = timezone.now()
            other.append(
                ScanRun.objects.create(
                    query="topic:llm", status=ScanRun.Status.RUNNING, heartbeat_at=now
                )
            )

    fake.search.on_query = manual_scan_wins_the_race

    run = run_daily_now()

    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.RETRY_LATER)
    assert f"#{other[0].pk}" in run.stop_reason
    assert calls_for(fake, B) == 0
    assert run.scans.count() == 1


def test_interrupted_mid_rescan_continues_without_rescanning_finished_queries(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())

    def app_closes_on_second_page_of_b(sent: str) -> None:
        if sent.startswith(f"{B} ") and calls_for(fake, B) == 2:
            raise AppKilledError

    fake.search.on_query = app_closes_on_second_page_of_b
    run = services.prepare_daily_run()
    with pytest.raises(AppKilledError):
        services.execute_daily_run(run.pk)
    fake.search.on_query = None
    make_heartbeats_stale()

    continued = services.run_daily_if_due()  # nhịp sau: thấy bị gián đoạn → tự chạy tiếp

    assert continued is not None
    assert (continued.pk, continued.status) == (run.pk, Status.SUCCEEDED)
    assert continued.auto_continue_count == 1
    assert calls_for(fake, A) == 3  # không quét lại truy vấn đã xong
    assert calls_for(fake, B) == 2 + 3  # lát dở làm lại từ trang 1
    assert calls_for(fake, C) == 3
    assert continued.scans.count() == 3
    assert {link.scan_run.fetched_count for link in continued.scans.select_related("scan_run")} == {
        250
    }
    assert continued.search_calls_used == 3 + 5 + 3


def test_live_daily_run_uses_child_scan_heartbeat(watch_list: list[WatchQuery]) -> None:
    run = services.prepare_daily_run()
    child = discovery.start_scan(
        discovery.ScanRequest(A, 10, None, None, None, budget=300, origin=ScanRun.Origin.DAILY)
    )
    DailyRunScan.objects.create(
        daily_run=run, watch_query=watch_list[0], scan_run=child, position=1
    )
    long_ago = timezone.now() - timedelta(minutes=10)
    DailyRun.objects.filter(pk=run.pk).update(heartbeat_at=long_ago)

    assert services.live_daily_run() == run
    assert services.pause_stale_daily_runs() == 0

    ScanRun.objects.filter(pk=child.pk).update(heartbeat_at=long_ago)

    assert services.live_daily_run() is None


@pytest.mark.parametrize("status", [Status.SUCCEEDED, Status.SUCCEEDED_PARTIAL])
def test_prepare_refuses_when_today_succeeded(status: str) -> None:
    DailyRun.objects.create(day=timezone.localdate(), status=status)

    with pytest.raises(services.DailyRunBlockedError, match="Hôm nay đã quét xong"):
        services.prepare_daily_run()


def test_prepare_reopens_failed_run() -> None:
    failed = DailyRun.objects.create(
        day=timezone.localdate(),
        status=Status.FAILED,
        error_message="Truy vấn «topic:seo»: GitHub từ chối token.",
        stop_reason="lý do cũ",
        runner_token="ma-cu",
        stop_requested=True,
        finished_at=timezone.now(),
    )

    run = services.prepare_daily_run()

    assert run.pk == failed.pk
    assert run.status == Status.RUNNING
    assert (run.error_message, run.stop_reason, run.runner_token) == ("", "", "")
    assert run.stop_requested is False
    assert run.finished_at is None
    assert services.live_daily_run() == run


def test_prepare_refuses_while_another_scan_or_daily_run_is_live() -> None:
    manual = discovery.start_scan(manual_request())

    with pytest.raises(services.DailyRunBlockedError, match=f"#{manual.pk}"):
        services.prepare_daily_run()
    assert not DailyRun.objects.exists()

    ScanRun.objects.filter(pk=manual.pk).update(status=ScanRun.Status.SUCCEEDED)
    services.prepare_daily_run()

    with pytest.raises(services.DailyRunBlockedError, match="đang chạy"):
        services.prepare_daily_run()


def test_empty_watch_list_finishes_with_note(use_fake: UseFake) -> None:
    WatchQuery.objects.update(enabled=False)  # tắt hết cũng là trống
    fake = use_fake(some_repos())

    run = run_daily_now()

    assert run.status == Status.SUCCEEDED_PARTIAL
    assert run.problems == ["Danh sách theo dõi trống — thêm truy vấn ở trang Theo dõi."]
    assert run.scans.count() == 0
    assert fake.search.queries == []
    assert run.search_calls_used == 0


def test_watch_query_deleted_mid_run_keeps_scan_link(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())

    def edit_watch_list_while_b_runs(sent: str) -> None:
        if sent.startswith(f"{B} "):
            WatchQuery.objects.filter(query=B).delete()
            WatchQuery.objects.filter(query=C).update(enabled=False)

    fake.search.on_query = edit_watch_list_while_b_runs

    run = run_daily_now()

    assert run.status == Status.SUCCEEDED
    link = run.scans.select_related("scan_run").get(scan_run__query=B)
    assert link.watch_query is None
    assert link.scan_run.status == ScanRun.Status.SUCCEEDED
    assert run.scans.count() == 2
    assert calls_for(fake, C) == 0


def test_superseded_runner_withdraws_without_writing(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = use_fake(some_repos())

    def taken_over_elsewhere(sent: str) -> None:
        if sent.startswith(f"{B} "):
            DailyRun.objects.update(runner_token="tien-trinh-khac")

    fake.search.on_query = taken_over_elsewhere
    run = services.prepare_daily_run()

    services.execute_daily_run(run.pk)  # luồng cũ rút lui êm, không ném lỗi

    run.refresh_from_db()
    assert (run.status, run.runner_token) == (Status.RUNNING, "tien-trinh-khac")
    assert run.search_calls_used == 3  # chỉ phần ghi khi còn giữ lượt
    assert calls_for(fake, C) == 0


def test_execute_skips_run_already_held_by_another_runner(use_fake: UseFake) -> None:
    fake = use_fake(some_repos())
    run = services.prepare_daily_run()
    DailyRun.objects.filter(pk=run.pk).update(runner_token="tien-trinh-khac")

    services.execute_daily_run(run.pk)

    run.refresh_from_db()
    assert (run.status, run.runner_token) == (Status.RUNNING, "tien-trinh-khac")
    assert fake.search.queries == []


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github
