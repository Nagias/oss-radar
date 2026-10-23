"""Kho repo: ghi không trùng — cùng một repo GitHub (cùng github_id) luôn chỉ là MỘT dòng."""

from datetime import UTC, date, datetime, timedelta

import pytest

from features.catalog.models import Repository, StarSnapshot
from features.catalog.services import (
    StarPoint,
    baseline_snapshots,
    prune_snapshots,
    upsert_repositories,
)
from tests.factories import make_github_repo

pytestmark = pytest.mark.django_db

FIRST_SEEN = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
LATER = FIRST_SEEN + timedelta(days=1)


def test_upsert_stores_new_repositories() -> None:
    repos = [
        make_github_repo(github_id=1, full_name="a/one", stars=10),
        make_github_repo(github_id=2, full_name="b/two", stars=20, license_spdx=""),
    ]

    outcomes = upsert_repositories(repos, seen_at=FIRST_SEEN)

    assert [(o.repository.full_name, o.created) for o in outcomes] == [
        ("a/one", True),
        ("b/two", True),
    ]
    stored = Repository.objects.get(github_id=1)
    assert stored.stars == 10
    assert stored.owner_type == "Organization"
    assert stored.topics == ["agent", "claude-code"]
    assert stored.license_spdx == "MIT"
    assert stored.gh_created_at == datetime(2025, 6, 29, 15, 34, 15, tzinfo=UTC)
    assert stored.first_seen_at == FIRST_SEEN
    assert stored.last_seen_at == FIRST_SEEN


def test_upsert_same_repo_again_updates_instead_of_duplicating() -> None:
    upsert_repositories([make_github_repo(github_id=7, stars=10)], seen_at=FIRST_SEEN)

    outcomes = upsert_repositories([make_github_repo(github_id=7, stars=25)], seen_at=LATER)

    assert Repository.objects.count() == 1
    assert outcomes[0].created is False
    stored = Repository.objects.get(github_id=7)
    assert stored.stars == 25
    assert stored.first_seen_at == FIRST_SEEN
    assert stored.last_seen_at == LATER


def test_upsert_follows_rename_by_github_id() -> None:
    upsert_repositories([make_github_repo(github_id=9, full_name="old/name")], seen_at=FIRST_SEEN)

    upsert_repositories([make_github_repo(github_id=9, full_name="new/name")], seen_at=LATER)

    assert list(Repository.objects.values_list("full_name", flat=True)) == ["new/name"]


def test_upsert_ignores_duplicates_inside_one_batch() -> None:
    repo = make_github_repo(github_id=3)

    outcomes = upsert_repositories([repo, repo], seen_at=FIRST_SEEN)

    assert len(outcomes) == 1
    assert Repository.objects.count() == 1


def test_repositories_are_listed_by_stars_descending() -> None:
    upsert_repositories(
        [
            make_github_repo(github_id=1, full_name="low/stars", stars=5),
            make_github_repo(github_id=2, full_name="high/stars", stars=500),
        ],
        seen_at=FIRST_SEEN,
    )

    assert [str(repo) for repo in Repository.objects.all()] == ["high/stars", "low/stars"]


@pytest.mark.parametrize(("owner_type", "expected"), [("Organization", True), ("User", False)])
def test_repository_knows_if_owned_by_organization(owner_type: str, expected: bool) -> None:
    upsert_repositories([make_github_repo(owner_type=owner_type)], seen_at=FIRST_SEEN)

    assert Repository.objects.get().is_organization is expected


# --- Ảnh chụp star theo ngày ---------------------------------------------------------------------

TODAY = date(2026, 10, 20)


def _snapshot_on(days_ago: int, *, github_id: int = 1, stars: int = 100) -> None:
    """Ghi repo vào kho như thể được thấy cách đây `days_ago` ngày (giờ Việt Nam)."""
    seen_at = FIRST_SEEN - timedelta(days=days_ago)
    upsert_repositories([make_github_repo(github_id=github_id, stars=stars)], seen_at=seen_at)


def test_upsert_records_snapshot_for_new_and_existing_repos() -> None:
    upsert_repositories([make_github_repo(github_id=1, stars=10)], seen_at=FIRST_SEEN)

    upsert_repositories(
        [
            make_github_repo(github_id=1, stars=12),
            make_github_repo(github_id=2, full_name="b/two", stars=20),
        ],
        seen_at=LATER,
    )

    rows = StarSnapshot.objects.order_by("repository__github_id", "day")
    assert [(r.repository.github_id, r.day, r.stars, r.captured_at) for r in rows] == [
        (1, date(2026, 10, 20), 10, FIRST_SEEN),
        (1, date(2026, 10, 21), 12, LATER),
        (2, date(2026, 10, 21), 20, LATER),
    ]


def test_upsert_twice_same_day_keeps_one_snapshot_with_latest_stars() -> None:
    upsert_repositories([make_github_repo(github_id=1, stars=100)], seen_at=FIRST_SEEN)
    later_same_day = FIRST_SEEN + timedelta(hours=2)

    upsert_repositories([make_github_repo(github_id=1, stars=120)], seen_at=later_same_day)

    snapshot = StarSnapshot.objects.get()
    assert snapshot.stars == 120
    assert snapshot.captured_at == later_same_day


def test_upsert_next_day_adds_second_snapshot() -> None:
    upsert_repositories([make_github_repo(github_id=1, stars=100)], seen_at=FIRST_SEEN)

    upsert_repositories([make_github_repo(github_id=1, stars=130)], seen_at=LATER)

    assert list(StarSnapshot.objects.order_by("day").values_list("day", "stars")) == [
        (date(2026, 10, 20), 100),
        (date(2026, 10, 21), 130),
    ]


def test_snapshot_is_described_by_repository_day_and_stars() -> None:
    upsert_repositories([make_github_repo(github_id=1, stars=10)], seen_at=FIRST_SEEN)

    snapshot = StarSnapshot.objects.get()

    assert str(snapshot) == f"{snapshot.repository_id} @ 2026-10-20: 10"


def test_snapshot_day_follows_vietnam_local_date_not_utc() -> None:
    # 20:00 UTC ngày 20 = 03:00 ngày 21 giờ Việt Nam.
    seen_at = datetime(2026, 10, 20, 20, 0, tzinfo=UTC)

    upsert_repositories([make_github_repo(github_id=1)], seen_at=seen_at)

    assert StarSnapshot.objects.get().day == date(2026, 10, 21)


def test_baseline_prefers_oldest_within_window() -> None:
    for days_ago, stars in [(9, 50), (6, 60), (2, 80)]:
        _snapshot_on(days_ago, stars=stars)

    baseline = baseline_snapshots(today=TODAY)

    repo_id = Repository.objects.get().pk
    assert baseline == {repo_id: StarPoint(day=TODAY - timedelta(days=6), stars=60)}


def test_baseline_window_includes_exactly_window_days_ago() -> None:
    for days_ago, stars in [(8, 40), (7, 50), (1, 90)]:
        _snapshot_on(days_ago, stars=stars)

    baseline = baseline_snapshots(today=TODAY, window_days=7)

    assert list(baseline.values()) == [StarPoint(day=TODAY - timedelta(days=7), stars=50)]


def test_baseline_falls_back_to_latest_older_snapshot() -> None:
    for days_ago, stars in [(20, 30), (9, 50)]:
        _snapshot_on(days_ago, stars=stars)

    baseline = baseline_snapshots(today=TODAY)

    assert list(baseline.values()) == [StarPoint(day=TODAY - timedelta(days=9), stars=50)]


def test_baseline_ignores_today_and_omits_repos_without_history() -> None:
    _snapshot_on(0, github_id=1, stars=70)  # chỉ có ảnh chụp hôm nay
    _snapshot_on(0, github_id=2, stars=90)
    _snapshot_on(1, github_id=2, stars=85)

    baseline = baseline_snapshots(today=TODAY)

    only_with_history = Repository.objects.get(github_id=2).pk
    assert baseline == {only_with_history: StarPoint(day=TODAY - timedelta(days=1), stars=85)}


def test_baseline_keeps_each_repository_separate() -> None:
    _snapshot_on(5, github_id=1, stars=10)
    _snapshot_on(20, github_id=2, stars=30)

    baseline = baseline_snapshots(today=TODAY)

    ids = {r.github_id: r.pk for r in Repository.objects.all()}
    assert baseline == {
        ids[1]: StarPoint(day=TODAY - timedelta(days=5), stars=10),
        ids[2]: StarPoint(day=TODAY - timedelta(days=20), stars=30),
    }


def test_prune_snapshots_deletes_only_older_days() -> None:
    for days_ago in (40, 36, 35, 1):
        _snapshot_on(days_ago)

    deleted = prune_snapshots(before=TODAY - timedelta(days=35))

    assert deleted == 2
    assert sorted(StarSnapshot.objects.values_list("day", flat=True)) == [
        TODAY - timedelta(days=35),
        TODAY - timedelta(days=1),
    ]


def test_upsert_stores_open_issue_count() -> None:
    upsert_repositories([make_github_repo(github_id=3, open_issues=12)], seen_at=FIRST_SEEN)
    upsert_repositories([make_github_repo(github_id=3, open_issues=0)], seen_at=LATER)

    assert Repository.objects.get(github_id=3).open_issues == 0


def test_repository_saved_without_issue_count_keeps_it_unknown() -> None:
    # Repo lưu trước F-006 (chưa được quét lại) chưa biết số issue/PR đang mở: để trống, không là 0.
    upsert_repositories([make_github_repo(github_id=4)], seen_at=FIRST_SEEN)
    Repository.objects.filter(github_id=4).update(open_issues=None)

    assert Repository.objects.get(github_id=4).open_issues is None
