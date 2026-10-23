"""Dịch vụ chấm điểm: gom dữ kiện từ kho, dùng hồ sơ chủ đã lưu, lấy hồ sơ chủ có ngân sách."""

from datetime import UTC, date, datetime, timedelta

import pytest
import respx
from django.template.loader import render_to_string
from django.utils import timezone

from features.catalog.models import OwnerProfile, Repository
from features.catalog.services import mark_owner_missing, save_owner_profile, upsert_repositories
from features.scoring import services
from features.scoring.rules import GrowthFacts, RepoFacts, SuspicionLevel, quality_score
from integrations.github.client import get_github_client
from integrations.github.errors import GitHubUnavailableError
from integrations.github.pacing import CallBudget, CallBudgetExhaustedError
from integrations.github.schemas import GitHubUser
from tests.factories import make_github_repo
from tests.fakes import FakeGitHubUsers, FakeTime, make_user

pytestmark = pytest.mark.django_db

USERS_URL = r"^https://api\.github\.com/users/[^/]+$"
CREATED = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)


def store(github_id: int, **changes: object) -> Repository:
    fields: dict[str, object] = {
        "github_id": github_id,
        "full_name": f"chu-{github_id}/repo",
        "html_url": f"https://github.com/chu-{github_id}/repo",
        "owner_login": f"Chu-{github_id}",
        "owner_type": "User",
    }
    fields.update(changes)
    [outcome] = upsert_repositories([make_github_repo(**fields)], seen_at=timezone.now())
    return outcome.repository


def profile(login: str, *, created: datetime, followers: int = 0, repos: int = 2) -> GitHubUser:
    return GitHubUser(
        login=login,
        github_id=1,
        account_type="User",
        created_at=created,
        followers=followers,
        public_repos=repos,
    )


# --- Dữ kiện và điểm -------------------------------------------------------------------------


def test_repo_facts_come_from_catalog_fields() -> None:
    repo = store(
        1,
        stars=613,
        forks=2,
        open_issues=0,
        owner_type="Organization",
        license_spdx="MIT",
        description="mô tả",
        topics=("a", "b", "c", "d"),
        is_archived=True,
        created_at=CREATED,
        pushed_at=CREATED,
    )

    assert services.repo_facts(repo) == RepoFacts(
        stars=613,
        forks=2,
        open_issues=0,
        is_organization=True,
        license_spdx="MIT",
        description="mô tả",
        topic_count=4,
        is_archived=True,
        created_at=CREATED,
        pushed_at=CREATED,
    )


def test_scores_use_stored_owner_profile_case_insensitively() -> None:
    repo = store(1, stars=613, forks=2, created_at=CREATED, pushed_at=CREATED)
    save_owner_profile(
        profile("chu-1", created=datetime(2026, 3, 2, tzinfo=UTC)), fetched_at=timezone.now()
    )

    [scores] = services.score_repositories([repo]).values()

    assert scores.suspicion.points == 75
    assert scores.suspicion.level == SuspicionLevel.HIGH
    assert scores.suspicion.notes == ()
    assert scores.potential is None
    assert (
        scores.quality.total == quality_score(services.repo_facts(repo), now=timezone.now()).total
    )


def test_scores_say_when_owner_account_is_gone() -> None:
    repo = store(2, stars=500, forks=50)
    mark_owner_missing("CHU-2", fetched_at=timezone.now())

    [scores] = services.score_repositories([repo]).values()

    assert scores.suspicion.notes == ("tài khoản chủ repo không còn tồn tại trên GitHub",)


def test_scores_without_owner_profile_note_it() -> None:
    repo = store(3, stars=500, forks=50)

    [scores] = services.score_repositories([repo]).values()

    assert scores.suspicion.notes == ("chưa có hồ sơ chủ repo — chưa tính phần hồ sơ chủ",)


def test_growth_given_by_caller_adds_potential_keyed_by_repository() -> None:
    with_growth = store(4, stars=640)
    without = store(5, stars=640)
    growth = GrowthFacts(stars=640, gain_7d=100, gain_30d=150, series=(), estimated=True)

    scores = services.score_repositories([with_growth, without], growth={with_growth.pk: growth})

    potential = scores[with_growth.pk].potential
    assert potential is not None
    assert potential.estimated is True
    assert scores[without.pk].potential is None


def test_scoring_reads_owner_profiles_in_one_query(
    django_assert_max_num_queries: pytest.FixtureRequest,
) -> None:
    repos = [store(github_id, stars=500, forks=50) for github_id in range(10, 20)]

    with django_assert_max_num_queries(1):  # type: ignore[operator]
        scores = services.score_repositories(repos)

    assert len(scores) == 10


# --- Chọn chủ cần lấy hồ sơ ------------------------------------------------------------------


def test_owners_to_fetch_skips_profiles_younger_than_30_days() -> None:
    now = timezone.now()
    save_owner_profile(profile("fresh", created=CREATED), fetched_at=now - timedelta(days=29))
    save_owner_profile(profile("stale", created=CREATED), fetched_at=now - timedelta(days=31))

    needed = services.owners_to_fetch(["fresh", "Stale", "new", "NEW"], now=now)

    assert needed == ["Stale", "new"]


# --- Lấy hồ sơ chủ ---------------------------------------------------------------------------


@pytest.fixture
def users(http_mock: respx.MockRouter) -> FakeGitHubUsers:
    fake = FakeGitHubUsers(
        {
            "alice": make_user("alice", created=date(2015, 5, 1), followers=120, public_repos=40),
            "bob": make_user("bob", created=date(2026, 3, 2), followers=0, public_repos=2),
        }
    )
    http_mock.get(url__regex=USERS_URL).mock(side_effect=fake)
    return fake


class Calls:
    def __init__(self) -> None:
        self.before = 0
        self.after = 0

    def before_each(self) -> None:
        self.before += 1

    def after_call(self) -> None:
        self.after += 1


def test_fetch_saves_profiles_and_marks_missing_accounts(
    users: FakeGitHubUsers, fake_time: FakeTime
) -> None:
    calls = Calls()

    with get_github_client(sleep=fake_time.sleep) as github:
        outcome = services.fetch_owner_profiles(
            github,
            ["Alice", "bob", "ghost"],
            before_each=calls.before_each,
            after_call=calls.after_call,
        )

    assert (outcome.fetched, outcome.missing, outcome.unreadable) == (2, 1, [])
    assert users.requested == ["Alice", "bob", "ghost"]
    assert (calls.before, calls.after) == (3, 3)
    alice = OwnerProfile.objects.get(login="alice")
    assert (alice.followers, alice.public_repos) == (120, 40)
    assert OwnerProfile.objects.get(login="ghost").is_missing is True


def test_fetch_skips_unreadable_profiles_and_goes_on(
    users: FakeGitHubUsers, fake_time: FakeTime
) -> None:
    users.users["broken"] = {"login": "broken"}  # thiếu trường: GitHub trả dữ liệu lạ
    calls = Calls()

    with get_github_client(sleep=fake_time.sleep) as github:
        outcome = services.fetch_owner_profiles(
            github,
            ["broken", "bad login", "alice"],
            before_each=calls.before_each,
            after_call=calls.after_call,
        )

    assert outcome.fetched == 1
    assert [login for login, _ in outcome.unreadable] == ["broken", "bad login"]
    assert "sai định dạng" in outcome.unreadable[0][1]
    assert users.requested == ["broken", "alice"]  # login lạ không được gửi đi
    assert calls.before == 3
    assert OwnerProfile.objects.filter(login="broken").exists() is False


def test_fetch_stops_on_github_outage_keeping_profiles_already_saved(
    users: FakeGitHubUsers, fake_time: FakeTime
) -> None:
    users.fail_when = lambda login: 503 if login == "bob" else None
    calls = Calls()

    with (
        get_github_client(sleep=fake_time.sleep) as github,
        pytest.raises(GitHubUnavailableError),
    ):
        services.fetch_owner_profiles(
            github, ["alice", "bob"], before_each=calls.before_each, after_call=calls.after_call
        )

    assert list(OwnerProfile.objects.values_list("login", flat=True)) == ["alice"]
    assert calls.after == 2


def test_fetch_stops_when_budget_runs_out(users: FakeGitHubUsers, fake_time: FakeTime) -> None:
    calls = Calls()

    with (
        get_github_client(sleep=fake_time.sleep, budget=CallBudget(1)) as github,
        pytest.raises(CallBudgetExhaustedError),
    ):
        services.fetch_owner_profiles(
            github, ["alice", "bob"], before_each=calls.before_each, after_call=calls.after_call
        )

    assert users.requested == ["alice"]
    assert OwnerProfile.objects.count() == 1


# --- Template con ----------------------------------------------------------------------------


def test_score_partial_lists_every_component() -> None:
    repo = store(30, stars=1000, forks=100, open_issues=3)
    growth = GrowthFacts(stars=1000, gain_7d=100, gain_30d=None, series=(), estimated=True)
    scores = services.score_repositories([repo], growth={repo.pk: growth})[repo.pk]

    quality_html = render_to_string("scoring/_score.html", {"score": scores.quality})
    potential_html = render_to_string("scoring/_score.html", {"score": scores.potential})
    empty_html = render_to_string("scoring/_score.html", {"score": None})

    assert f"<strong>{scores.quality.total}</strong>" in quality_html
    assert "Phổ biến <strong>20/30</strong> — 1.000 star" in quality_html
    assert "(ước lượng)" in potential_html
    assert "chưa xác minh" in potential_html
    assert empty_html.strip() == "—"


def test_suspicion_partial_shows_label_points_and_reasons() -> None:
    risky = store(31, stars=613, forks=2, created_at=CREATED, pushed_at=CREATED)
    small = store(32, stars=50)
    clean = store(33, stars=1000, forks=100)
    scores = services.score_repositories([risky, small, clean])

    risky_html = render_to_string(
        "scoring/_suspicion.html", {"suspicion": scores[risky.pk].suspicion}
    )
    small_html = render_to_string(
        "scoring/_suspicion.html", {"suspicion": scores[small.pk].suspicion}
    )
    clean_html = render_to_string(
        "scoring/_suspicion.html", {"suspicion": scores[clean.pk].suspicion}
    )

    assert "Nghi cao" in risky_html
    assert "+45 — 2 fork trên 613 star (dưới 0,5%)" in risky_html
    assert "+20 — không có commit nào sau ngày tạo" in risky_html
    assert "chưa có hồ sơ chủ repo" in risky_html
    assert "—" in small_html
    assert "dưới 100 star" in small_html
    assert "Không nghi" in clean_html
    assert "không có dấu hiệu đáng ngờ" in clean_html
