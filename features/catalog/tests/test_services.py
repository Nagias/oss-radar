"""Kho repo: ghi không trùng — cùng một repo GitHub (cùng github_id) luôn chỉ là MỘT dòng."""

from datetime import UTC, datetime, timedelta

import pytest

from features.catalog.models import Repository
from features.catalog.services import upsert_repositories
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
