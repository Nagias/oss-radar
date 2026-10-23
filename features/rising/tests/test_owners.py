"""Lượt hằng ngày, bước lấy hồ sơ chủ repo (F-006): chỉ chủ của rising star, có ngân sách.

Ba rising star của 2 chủ (một chủ viết hoa khác nhau ở hai repo) và một ứng viên không rising
(chủ thứ ba, không được gọi). Thứ tự gọi theo tăng 7 ngày giảm dần: OTHER (bob) rồi FAST (Alice).
"""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from pytest_django.fixtures import Settings

from features.catalog.models import OwnerProfile
from features.catalog.services import save_owner_profile
from features.rising import growth, services
from features.rising.models import DailyRun, WatchQuery
from features.rising.tests.conftest import (
    AppKilledError,
    FakeGitHub,
    UseFake,
    days_ago,
    history,
    item,
    make_heartbeats_stale,
    snapshot,
)
from features.scoring import rules
from integrations.github.schemas import GitHubUser
from tests.fakes import make_user

pytestmark = pytest.mark.django_db

Status = DailyRun.Status
PauseKind = DailyRun.PauseKind
Step = DailyRun.Step

FAST, MID, NEWBORN, OTHER = 301, 302, 303, 304


def users() -> dict[str, dict[str, Any]]:
    return {
        "alice": make_user("alice", created=days_ago(3000), followers=120),
        "bob": make_user("bob", created=days_ago(200), followers=0, public_repos=2),
        "carol": make_user("carol", created=days_ago(3000)),
    }


def four_repos(use_fake: UseFake) -> FakeGitHub:
    """Rising: OTHER +140 (bob), FAST +70 (Alice), NEWBORN +50 (alice). MID +20 (carol): không."""
    snapshot(FAST, stars=100)
    return use_fake(
        [
            item(FAST, stars=160, owner="Alice"),
            item(MID, stars=200, created=days_ago(20), owner="carol"),
            item(NEWBORN, stars=60, created=days_ago(3), owner="alice"),
            item(OTHER, stars=300, created=days_ago(15), owner="bob"),
        ],
        {
            FAST: history(dict.fromkeys(range(30), 10)),
            MID: history({1: 10, 2: 10}),
            NEWBORN: history({0: 25, 1: 25}),
            OTHER: history(dict.fromkeys(range(7), 20)),
        },
        users(),
    )


def run_daily_now() -> DailyRun:
    run = services.prepare_daily_run()
    services.execute_daily_run(run.pk)
    run.refresh_from_db()
    return run


def test_owner_step_fetches_each_rising_owner_once(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = four_repos(use_fake)

    run = run_daily_now()

    assert run.rising_count == 3
    assert fake.users.requested == ["bob", "Alice"]
    assert set(OwnerProfile.objects.values_list("login", flat=True)) == {"alice", "bob"}
    assert (run.owner_budget, run.owner_calls_used) == (10, 2)
    assert (run.status, run.step, run.problems) == (Status.SUCCEEDED, Step.REPORT, [])


def test_owner_budget_with_token_is_100(
    watch_list: list[WatchQuery], use_fake: UseFake, settings: Settings
) -> None:
    settings.GITHUB_TOKEN = "test-token"
    four_repos(use_fake)

    run = run_daily_now()

    assert (run.owner_budget, run.owner_calls_used) == (100, 2)


def test_fresh_profiles_are_not_fetched_again_stale_ones_are(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    now = timezone.now()
    alice = GitHubUser("alice", 1, "User", now - timedelta(days=3000), 120, 30)
    bob = GitHubUser("bob", 2, "User", now - timedelta(days=200), 0, 2)
    save_owner_profile(alice, fetched_at=now - timedelta(days=29))
    save_owner_profile(bob, fetched_at=now - timedelta(days=31))
    fake = four_repos(use_fake)

    run = run_daily_now()

    assert fake.users.requested == ["bob"]
    assert run.owner_calls_used == 1


def test_owner_budget_exhausted_notes_owners_left_and_run_finishes(
    watch_list: list[WatchQuery], use_fake: UseFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "OWNER_BUDGET_ANONYMOUS", 1)
    fake = four_repos(use_fake)

    run = run_daily_now()

    assert fake.users.requested == ["bob"]
    assert run.status == Status.SUCCEEDED_PARTIAL
    assert run.problems == [
        "Hết ngân sách hồ sơ chủ repo — 1 chủ repo chưa có hồ sơ (điểm nghi star giả của repo "
        "đó chưa tính phần hồ sơ chủ)."
    ]
    assert (run.owner_budget, run.owner_calls_used) == (1, 1)
    assert run.step == Step.REPORT


def test_deleted_owner_account_is_recorded_and_run_continues(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = four_repos(use_fake)
    del fake.users.users["bob"]

    run = run_daily_now()

    assert fake.users.requested == ["bob", "Alice"]
    assert OwnerProfile.objects.get(login="bob").is_missing is True
    assert (run.status, run.problems) == (Status.SUCCEEDED, [])


def test_unreadable_owner_profile_is_noted_and_run_continues(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = four_repos(use_fake)
    fake.users.users["bob"] = {"login": "bob"}  # GitHub trả dữ liệu thiếu trường

    run = run_daily_now()

    assert fake.users.requested == ["bob", "Alice"]
    assert run.status == Status.SUCCEEDED_PARTIAL
    assert len(run.problems) == 1
    assert run.problems[0].startswith("Không đọc được hồ sơ chủ repo bob")


def test_interrupted_owner_step_continues_without_refetching(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = four_repos(use_fake)
    killed: list[str] = []

    def app_closes_on_alice(login: str) -> int | None:
        if login == "Alice" and not killed:
            killed.append(login)
            raise AppKilledError
        return None

    fake.users.fail_when = app_closes_on_alice
    run = services.prepare_daily_run()
    with pytest.raises(AppKilledError):
        services.execute_daily_run(run.pk)
    run.refresh_from_db()
    assert (run.step, run.owner_calls_used) == (Step.OWNERS, 2)
    fake.users.fail_when = None
    make_heartbeats_stale()

    continued = services.run_daily_if_due()

    assert continued is not None
    assert continued.status == Status.SUCCEEDED
    assert fake.users.requested == ["bob", "Alice", "Alice"]
    assert continued.owner_calls_used == 3  # lượt gọi đã tiêu lúc sập không được "hoàn"


@pytest.mark.parametrize("status", [429, 502])
def test_github_blocking_owner_step_pauses_for_retry_later(
    watch_list: list[WatchQuery], use_fake: UseFake, status: int
) -> None:
    fake = four_repos(use_fake)
    fake.users.fail_when = lambda login: status if login == "Alice" else None

    run = run_daily_now()

    assert (run.status, run.pause_kind, run.step) == (
        Status.PAUSED,
        PauseKind.RETRY_LATER,
        Step.OWNERS,
    )
    assert "hồ sơ chủ repo" in run.stop_reason
    assert "15 phút" in run.stop_reason

    fake.users.fail_when = None
    DailyRun.objects.update(paused_at=timezone.now() - timedelta(minutes=16))
    continued = services.run_daily_if_due()

    assert continued is not None
    assert continued.status == Status.SUCCEEDED
    assert OwnerProfile.objects.filter(login="alice").exists()


def test_auth_error_in_owner_step_fails_run(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = four_repos(use_fake)
    fake.users.fail_when = lambda login: 401

    run = run_daily_now()

    assert run.status == Status.FAILED
    assert "hồ sơ chủ repo" in run.error_message
    assert "GITHUB_TOKEN" in run.error_message
    assert run.runner_token == ""


def test_stop_during_owner_step_pauses_and_continue_finishes(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = four_repos(use_fake)

    def press_stop(login: str) -> int | None:
        if login == "bob" and not DailyRun.objects.filter(stop_requested=True).exists():
            services.request_daily_stop(DailyRun.objects.get())
        return None

    fake.users.fail_when = press_stop

    run = run_daily_now()

    assert (run.status, run.pause_kind, run.step) == (Status.PAUSED, PauseKind.STOPPED, Step.OWNERS)
    assert fake.users.requested == ["bob"]

    fake.users.fail_when = None
    continued = run_daily_now()

    assert continued.status == Status.SUCCEEDED
    assert fake.users.requested == ["bob", "Alice"]


# --- Trạng thái, ước lượng ---------------------------------------------------------------------


def test_headline_while_fetching_owner_profiles() -> None:
    DailyRun.objects.create(
        day=timezone.localdate(),
        status=Status.RUNNING,
        step=Step.OWNERS,
        heartbeat_at=timezone.now(),
        owner_budget=100,
        owner_calls_used=7,
    )

    assert services.today_status().headline == (
        "Đang chạy: lấy hồ sơ chủ repo của rising star — đã dùng 7/100 lượt gọi."
    )


def test_estimate_counts_owner_profile_calls() -> None:
    DailyRun.objects.create(
        day=timezone.localdate() - timedelta(days=1),
        status=Status.SUCCEEDED,
        step=Step.REPORT,
        search_calls_used=500,
        verify_calls_used=280,
        owner_calls_used=20,
    )

    assert services.daily_estimate().calls == 800


def test_burst_share_is_the_same_for_flags_and_suspicion() -> None:
    assert growth.BURST_SHARE == rules.BURST_SHARE


def test_owner_step_has_a_readable_name() -> None:
    assert Step.OWNERS.label == "Lấy hồ sơ chủ repo"


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github
