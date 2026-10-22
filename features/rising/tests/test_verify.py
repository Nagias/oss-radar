"""Lượt hằng ngày, bước 2 tới 4: lọc thô bằng ảnh chụp, xác minh bằng lịch sử star, lập báo cáo.

GitHub giả có Search (bước quét lại) và lịch sử star (bước xác minh). Ba truy vấn theo dõi của test
đều thấy mọi repo giả, nên mỗi repo nằm trong cả ba lần quét con.
"""

from datetime import date, timedelta
from typing import Any

import pytest
from django.utils import timezone
from pytest_django.fixtures import Settings

from features.catalog import services as catalog
from features.catalog.models import Repository, StarSnapshot
from features.discovery.models import ScanResult, ScanRun
from features.rising import services
from features.rising.models import DailyRun, RisingCheck, WatchQuery
from features.rising.tests.conftest import (
    AppKilledError,
    FakeGitHub,
    UseFake,
    days_ago,
    history,
    item,
    make_heartbeats_stale,
    snapshot,
    window_end,
)
from tests.fakes import FakeTime, make_search_items

pytestmark = pytest.mark.django_db

Status = DailyRun.Status
PauseKind = DailyRun.PauseKind
Source = RisingCheck.Source

RISER, SLOW, OLD_NO_BASELINE, YOUNG, BIG, FORK, ARCHIVED = 101, 102, 103, 104, 105, 106, 107
# Ba ứng viên dùng cho phần xác minh, ước lượng giảm dần: 140 (ảnh chụp), 70 và 60 (theo tuổi).
FAST, MID, NEWBORN = 201, 202, 203


def run_daily_now() -> DailyRun:
    run = services.prepare_daily_run()
    services.execute_daily_run(run.pk)
    run.refresh_from_db()
    return run


def check_of(github_id: int) -> RisingCheck:
    return RisingCheck.objects.select_related("repository").get(repository__github_id=github_id)


def three_candidates(use_fake: UseFake, histories: dict[int, list[dict[str, Any]]]) -> FakeGitHub:
    """FAST (ảnh chụp, ước lượng 140), MID (tuổi 20 ngày, 70), NEWBORN (tuổi 3 ngày, 60)."""
    snapshot(FAST, stars=100)
    return use_fake(
        [
            item(FAST, stars=160),
            item(MID, stars=200, created=days_ago(20)),
            item(NEWBORN, stars=60, created=days_ago(3), description=None),
        ],
        histories,
    )


def all_histories() -> dict[int, list[dict[str, Any]]]:
    return {
        FAST: history(dict.fromkeys(range(30), 10)),
        MID: history({1: 10, 2: 10}),
        NEWBORN: history({0: 45, 1: 5}),
    }


# --- Lọc thô ---------------------------------------------------------------------------------


def test_screen_picks_candidates_from_snapshot_and_age_estimates(
    watch_list: list[WatchQuery], use_fake: UseFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ngân sách xác minh 0: giữ nguyên kết quả lọc thô để xem (không dòng nào được nâng cấp).
    monkeypatch.setattr(services, "VERIFY_BUDGET_WITH_TOKEN", 0)
    monkeypatch.setattr(services, "VERIFY_BUDGET_ANONYMOUS", 0)
    snapshot(RISER, stars=100)  # +60 trong 3 ngày → ước lượng 140
    snapshot(SLOW, stars=200)  # +2 trong 3 ngày → ước lượng 5
    snapshot(BIG, stars=900)
    snapshot(FORK, stars=100)
    snapshot(ARCHIVED, stars=100)
    fake = use_fake(
        [
            item(RISER, stars=160),
            item(SLOW, stars=202),
            item(OLD_NO_BASELINE, stars=300),
            item(YOUNG, stars=50, created=days_ago(10)),  # 50 star trong 10 ngày → ước lượng 35
            item(BIG, stars=1000),
            item(FORK, stars=300, fork=True),
            item(ARCHIVED, stars=300, archived=True),
        ]
    )

    run = run_daily_now()

    checks = {
        check.repository.github_id: (check.source, check.gain_7d, check.baseline_day, check.stars)
        for check in RisingCheck.objects.select_related("repository")
    }
    assert checks == {
        RISER: (Source.SNAPSHOT, 140, days_ago(3), 160),
        YOUNG: (Source.AGE, 35, None, 50),
    }
    assert not RisingCheck.objects.filter(is_rising=True).exists()
    assert (run.candidate_count, run.insufficient_count) == (2, 1)
    assert run.window_end == window_end()
    assert run.unverified_count == 2
    assert fake.history.requested == []
    assert run.problems == ["Hết ngân sách xác minh — 2 ứng viên chưa xác minh."]
    assert run.status == Status.SUCCEEDED_PARTIAL


def test_repo_in_two_watch_queries_checked_once(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = three_candidates(use_fake, all_histories())

    run = run_daily_now()

    assert run.scans.count() == 3  # cả ba truy vấn theo dõi đều thấy mọi repo
    assert RisingCheck.objects.filter(repository__github_id=FAST).count() == 1
    assert RisingCheck.objects.count() == 3
    assert sorted(fake.history.requested) == [FAST, MID, NEWBORN]


# --- Xác minh --------------------------------------------------------------------------------


def test_verify_upgrades_rows_with_official_gains_and_flags(
    watch_list: list[WatchQuery], use_fake: UseFake, settings: Settings
) -> None:
    settings.GITHUB_TOKEN = "test-token"
    fake = three_candidates(use_fake, all_histories())

    run = run_daily_now()

    assert fake.history.requested == [FAST, MID, NEWBORN]  # theo ước lượng giảm dần
    fast, mid, newborn = check_of(FAST), check_of(MID), check_of(NEWBORN)
    assert {check.source for check in (fast, mid, newborn)} == {Source.HISTORY}
    assert {check.window_end for check in (fast, mid, newborn)} == {window_end()}
    assert (fast.gain_1d, fast.gain_7d, fast.gain_30d) == (10, 70, 300)
    assert fast.series == [10] * 30
    assert (fast.is_rising, fast.flags) == (True, [])
    assert (mid.gain_1d, mid.gain_7d, mid.gain_30d, mid.is_rising) == (0, 20, 20, False)
    assert mid.flags == []
    assert (newborn.gain_1d, newborn.gain_7d, newborn.is_rising) == (45, 50, True)
    assert newborn.series[-2:] == [5, 45]
    assert newborn.flags == ["burst", "very_new", "no_description"]
    assert run.status == Status.SUCCEEDED
    assert run.problems == []
    assert (run.candidate_count, run.rising_count, run.unverified_count) == (3, 2, 0)
    assert (run.verify_budget, run.verify_calls_used) == (300, 3)
    assert run.step == DailyRun.Step.REPORT


def test_verify_budget_exhausted_leaves_rest_unverified_and_run_partial(
    watch_list: list[WatchQuery],
    use_fake: UseFake,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.GITHUB_TOKEN = "test-token"
    monkeypatch.setattr(services, "VERIFY_BUDGET_WITH_TOKEN", 2)
    fake = three_candidates(use_fake, all_histories())

    run = run_daily_now()

    assert fake.history.requested == [FAST, MID]
    left = check_of(NEWBORN)
    assert (left.source, left.gain_7d) == (Source.AGE, 60)
    assert run.status == Status.SUCCEEDED_PARTIAL
    assert run.problems == ["Hết ngân sách xác minh — 1 ứng viên chưa xác minh."]
    assert run.stop_reason == run.problems[0]
    assert (run.verify_budget, run.verify_calls_used) == (2, 2)
    assert (run.rising_count, run.unverified_count) == (1, 1)


def test_anonymous_uses_budget_50(
    watch_list: list[WatchQuery], use_fake: UseFake, settings: Settings
) -> None:
    settings.GITHUB_TOKEN = ""
    young = make_search_items(
        52, start=days_ago(20), end=days_ago(8), stars=lambda i: 100 + i, id_start=500
    )
    fake = use_fake(young, {repo["id"]: history({}) for repo in young})

    run = run_daily_now()

    assert run.candidate_count == 52
    assert (run.verify_budget, run.verify_calls_used) == (50, 50)
    assert len(fake.history.requested) == 50
    assert run.unverified_count == 2
    assert run.problems == ["Hết ngân sách xác minh — 2 ứng viên chưa xác minh."]


def test_deleted_repo_404_is_dropped_and_run_continues(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    histories = all_histories()
    del histories[MID]  # repo bị xoá (hoặc thành riêng tư) giữa lúc quét và lúc xác minh
    fake = three_candidates(use_fake, histories)

    run = run_daily_now()

    assert fake.history.requested == [FAST, MID, NEWBORN]
    assert set(RisingCheck.objects.values_list("repository__github_id", flat=True)) == {
        FAST,
        NEWBORN,
    }
    assert run.status == Status.SUCCEEDED
    assert run.problems == []
    assert run.verify_calls_used == 3


def test_unreadable_history_leaves_row_unverified_and_notes_repo(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = three_candidates(use_fake, all_histories())
    fake.history.fail_when = lambda repo_id: 418 if repo_id == MID else None

    run = run_daily_now()

    assert fake.history.requested == [FAST, MID, NEWBORN]
    assert check_of(MID).source == Source.AGE
    assert check_of(NEWBORN).source == Source.HISTORY
    assert run.status == Status.SUCCEEDED_PARTIAL
    assert len(run.problems) == 1
    assert "gia-lap/repo-202" in run.problems[0]
    assert run.unverified_count == 1


@pytest.mark.parametrize("status", [429, 502])
def test_rate_limit_during_verify_pauses_for_retry_later_and_continue_finishes(
    watch_list: list[WatchQuery], use_fake: UseFake, status: int
) -> None:
    fake = three_candidates(use_fake, all_histories())
    fake.history.fail_when = lambda repo_id: status if repo_id == MID else None

    run = run_daily_now()

    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.RETRY_LATER)
    assert "15 phút" in run.stop_reason
    assert run.step == DailyRun.Step.VERIFY
    assert fake.history.requested == [FAST] + [MID] * 4  # GitHub chặn: chờ / gọi lại 3 lần
    assert run.verify_calls_used == 5

    fake.history.fail_when = None
    DailyRun.objects.update(paused_at=timezone.now() - timedelta(minutes=16))
    continued = services.run_daily_if_due()  # nhịp sau, đã chờ đủ 15 phút

    assert continued is not None
    assert (continued.pk, continued.status) == (run.pk, Status.SUCCEEDED)
    assert continued.auto_continue_count == 1
    assert fake.history.requested == [FAST] + [MID] * 5 + [NEWBORN]
    assert continued.verify_calls_used == 7
    assert continued.rising_count == 2


def test_auth_error_during_verify_fails_run(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = three_candidates(use_fake, all_histories())
    fake.history.fail_when = lambda repo_id: 401 if repo_id == MID else None

    run = run_daily_now()

    assert run.status == Status.FAILED
    assert "GITHUB_TOKEN" in run.error_message
    assert fake.history.requested == [FAST, MID]
    assert run.verify_calls_used == 2
    assert run.runner_token == ""


@pytest.mark.parametrize("pressed", ["between_repos", "while_waiting_for_github"])
def test_stop_during_verify_pauses_run_and_continue_finishes(
    watch_list: list[WatchQuery], use_fake: UseFake, fake_time: FakeTime, pressed: str
) -> None:
    fake = three_candidates(use_fake, all_histories())

    def press_stop(repo_id: int) -> int | None:
        if repo_id != MID or DailyRun.objects.filter(stop_requested=True).exists():
            return None
        services.request_daily_stop(DailyRun.objects.get())
        # Đang chờ GitHub hồi lượt (429) thì nút Dừng có tác dụng ngay trong lúc chờ.
        return 429 if pressed == "while_waiting_for_github" else None

    fake.history.fail_when = press_stop

    run = run_daily_now()

    assert (run.status, run.pause_kind) == (Status.PAUSED, PauseKind.STOPPED)
    assert run.stop_reason == services.REASON_STOPPED
    assert fake.history.requested == [FAST, MID]
    assert all(seconds <= 10 for seconds in fake_time.sleeps)  # ngủ từng khúc, ghi nhịp sống

    fake.history.fail_when = None
    continued = run_daily_now()  # bấm "Chạy tiếp"

    assert continued.status == Status.SUCCEEDED
    expected = [FAST, MID, NEWBORN] if pressed == "between_repos" else [FAST, MID, MID, NEWBORN]
    assert fake.history.requested == expected


def test_interrupted_during_verify_continues_without_recalling_verified_rows(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = three_candidates(use_fake, all_histories())
    killed: list[int] = []

    def app_closes_on_mid(repo_id: int) -> int | None:
        if repo_id == MID and not killed:
            killed.append(repo_id)
            raise AppKilledError
        return None

    fake.history.fail_when = app_closes_on_mid
    run = services.prepare_daily_run()
    with pytest.raises(AppKilledError):
        services.execute_daily_run(run.pk)
    fake.history.fail_when = None
    make_heartbeats_stale()

    continued = services.run_daily_if_due()  # nhịp sau: thấy bị gián đoạn → tự chạy tiếp

    assert continued is not None
    assert (continued.pk, continued.status) == (run.pk, Status.SUCCEEDED)
    assert continued.auto_continue_count == 1
    assert fake.history.requested == [FAST, MID, MID, NEWBORN]  # FAST không bị gọi lại
    assert continued.verify_calls_used == 4  # lượt gọi bị cắt ngang vẫn được tính
    assert len(fake.search.queries) == 3  # không quét lại danh sách theo dõi
    assert RisingCheck.objects.filter(source=Source.HISTORY).count() == 3


def test_screen_restarted_after_crash_replaces_its_rows(
    watch_list: list[WatchQuery], use_fake: UseFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = three_candidates(use_fake, all_histories())
    real_baselines = catalog.baseline_snapshots
    crashed: list[date] = []

    def crash_once(*, today: date, window_days: int = 7) -> Any:
        if not crashed:
            crashed.append(today)
            raise AppKilledError
        return real_baselines(today=today, window_days=window_days)

    monkeypatch.setattr(catalog, "baseline_snapshots", crash_once)
    run = services.prepare_daily_run()
    with pytest.raises(AppKilledError):
        services.execute_daily_run(run.pk)
    assert DailyRun.objects.get().step == DailyRun.Step.SCREEN
    # Dòng ước lượng dở dang của lần lọc thô trước (một repo trùng, một repo nay không còn là ứng
    # viên): lọc lại phải thay hết, không sinh dòng trùng, không xác minh repo thừa.
    snapshot(SLOW, stars=10, days_back=1)
    for github_id, gain in ((FAST, 1), (SLOW, 999)):
        RisingCheck.objects.create(
            daily_run=run,
            repository=Repository.objects.get(github_id=github_id),
            stars=10,
            source=Source.SNAPSHOT,
            gain_7d=gain,
        )
    make_heartbeats_stale()

    continued = services.run_daily_if_due()

    assert continued is not None
    assert continued.status == Status.SUCCEEDED
    assert sorted(RisingCheck.objects.values_list("repository__github_id", flat=True)) == [
        FAST,
        MID,
        NEWBORN,
    ]
    assert continued.candidate_count == 3
    assert fake.history.requested == [FAST, MID, NEWBORN]
    assert len(fake.search.queries) == 3


def test_continued_run_keeps_original_verify_budget_and_window(
    watch_list: list[WatchQuery],
    use_fake: UseFake,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.GITHUB_TOKEN = "test-token"
    fake = three_candidates(use_fake, all_histories())
    fake.history.fail_when = lambda repo_id: 429 if repo_id == MID else None
    run = run_daily_now()
    assert (run.verify_budget, run.window_end) == (300, window_end())

    # Token bị gỡ trước khi chạy tiếp: lượt vẫn giữ ngân sách đã chốt lúc bắt đầu xác minh.
    settings.GITHUB_TOKEN = ""
    fake.history.fail_when = None
    stored_end = run.window_end
    assert stored_end is not None
    DailyRun.objects.update(window_end=stored_end - timedelta(days=1))
    continued = run_daily_now()

    assert continued.verify_budget == 300
    assert continued.window_end == stored_end - timedelta(days=1)
    assert check_of(NEWBORN).window_end == stored_end - timedelta(days=1)


# --- Lập báo cáo, dọn dữ liệu cũ -------------------------------------------------------------


def test_report_step_prunes_old_snapshots_and_daily_results(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    three_candidates(use_fake, all_histories())
    snapshot(900, stars=10, days_back=40)
    old_repo = StarSnapshot.objects.get(day=days_ago(40)).repository
    old_daily = ScanRun.objects.create(
        query="topic:cu", origin=ScanRun.Origin.DAILY, status=ScanRun.Status.SUCCEEDED
    )
    old_manual = ScanRun.objects.create(query="topic:cu", status=ScanRun.Status.SUCCEEDED)
    for scan in (old_daily, old_manual):
        ScanResult.objects.create(scan_run=scan, repository=old_repo, is_new=True)
    ScanRun.objects.filter(pk__in=[old_daily.pk, old_manual.pk]).update(
        created_at=timezone.now() - timedelta(days=40)
    )

    run = run_daily_now()

    assert run.status == Status.SUCCEEDED
    assert not StarSnapshot.objects.filter(day__lt=days_ago(35)).exists()
    assert StarSnapshot.objects.filter(day=days_ago(3)).exists()  # mốc gần vẫn giữ
    old_daily.refresh_from_db()
    assert (old_daily.results.count(), old_daily.results_pruned) == (0, True)
    assert old_manual.results.count() == 1  # lần quét tay không bị dọn
    for link in run.scans.select_related("scan_run"):
        assert link.scan_run.results.count() == 3  # lần quét hôm nay giữ nguyên


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github
