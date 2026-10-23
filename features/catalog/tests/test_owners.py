"""Hồ sơ chủ repo trong kho: một dòng mỗi chủ (khoá là login viết thường), lưu để không gọi lại."""

from datetime import UTC, datetime, timedelta

import pytest

from features.catalog.models import OwnerProfile
from features.catalog.services import (
    logins_needing_profile,
    mark_owner_missing,
    owner_profiles_for,
    save_owner_profile,
)
from integrations.github.schemas import GitHubUser

pytestmark = pytest.mark.django_db

FETCHED = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
LATER = FETCHED + timedelta(days=40)


def make_user(login: str = "Octocat", **changes: object) -> GitHubUser:
    fields: dict[str, object] = {
        "login": login,
        "github_id": 583231,
        "account_type": "User",
        "created_at": datetime(2011, 1, 25, 18, 44, 36, tzinfo=UTC),
        "followers": 24725,
        "public_repos": 8,
    }
    fields.update(changes)
    return GitHubUser(**fields)  # type: ignore[arg-type]


def test_save_stores_profile_under_lowercase_login() -> None:
    save_owner_profile(make_user("Octocat"), fetched_at=FETCHED)

    stored = OwnerProfile.objects.get()
    assert stored.login == "octocat"
    assert stored.github_id == 583231
    assert stored.account_type == "User"
    assert stored.gh_created_at == datetime(2011, 1, 25, 18, 44, 36, tzinfo=UTC)
    assert stored.followers == 24725
    assert stored.public_repos == 8
    assert stored.is_missing is False
    assert stored.fetched_at == FETCHED
    assert str(stored) == "octocat"


def test_save_again_overwrites_instead_of_duplicating() -> None:
    save_owner_profile(make_user("Octocat", followers=10), fetched_at=FETCHED)
    save_owner_profile(make_user("OCTOCAT", followers=11), fetched_at=LATER)

    stored = OwnerProfile.objects.get()
    assert stored.followers == 11
    assert stored.fetched_at == LATER


def test_missing_owner_clears_old_numbers_and_can_come_back() -> None:
    save_owner_profile(make_user("ghost"), fetched_at=FETCHED)

    mark_owner_missing("Ghost", fetched_at=LATER)
    gone = OwnerProfile.objects.get()
    assert gone.is_missing is True
    assert (gone.gh_created_at, gone.followers, gone.public_repos) == (None, None, None)
    assert gone.fetched_at == LATER

    save_owner_profile(make_user("ghost"), fetched_at=LATER + timedelta(days=1))
    assert OwnerProfile.objects.get().is_missing is False


def test_profiles_are_looked_up_case_insensitively() -> None:
    save_owner_profile(make_user("Octocat"), fetched_at=FETCHED)

    found = owner_profiles_for(["OctoCat", "nobody"])

    assert list(found) == ["octocat"]
    assert found["octocat"].followers == 24725


def test_profiles_lookup_handles_more_logins_than_sqlite_parameter_limit() -> None:
    OwnerProfile.objects.bulk_create(
        OwnerProfile(login=f"user-{index}", fetched_at=FETCHED) for index in range(1200)
    )

    found = owner_profiles_for([f"User-{index}" for index in range(1200)])

    assert len(found) == 1200


def test_logins_needing_profile_skips_fresh_keeps_order_and_dedupes() -> None:
    save_owner_profile(make_user("fresh"), fetched_at=LATER)
    save_owner_profile(make_user("stale"), fetched_at=FETCHED)

    needed = logins_needing_profile(
        ["Zed", "fresh", "Stale", "zed", "alpha", "ZED"], fresh_after=FETCHED + timedelta(days=1)
    )

    assert needed == ["Zed", "Stale", "alpha"]


def test_logins_needing_profile_handles_long_lists() -> None:
    logins = [f"user-{index}" for index in range(1200)]
    for login in logins[:600]:
        save_owner_profile(make_user(login), fetched_at=LATER)

    assert logins_needing_profile(logins, fresh_after=FETCHED) == logins[600:]
