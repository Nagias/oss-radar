"""Nghiệp vụ của kho repo. Tính năng khác muốn ghi bảng Repository phải đi qua đây."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from features.catalog.models import OwnerProfile, Repository, StarSnapshot
from integrations.github.schemas import GitHubRepo, GitHubUser

# SQLite giới hạn số tham số mỗi câu lệnh (~999): danh sách dài phải chia lô khi lọc `__in`.
_IN_BATCH = 500


@dataclass(frozen=True, slots=True)
class UpsertOutcome:
    repository: Repository
    created: bool


@dataclass(frozen=True, slots=True)
class StarPoint:
    """Số star của một repo vào một ngày — một mốc để so sánh mức tăng."""

    day: date
    stars: int


def upsert_repositories(repos: Iterable[GitHubRepo], *, seen_at: datetime) -> list[UpsertOutcome]:
    """Ghi repo vào kho: repo mới thì thêm, repo đã có (cùng github_id) thì cập nhật số liệu.

    Repo lặp lại trong cùng một lô chỉ được tính một lần. Trả về kết quả theo thứ tự đầu vào.
    Mỗi repo được ghi thêm ảnh chụp star của ngày `seen_at` (giờ Việt Nam), cùng transaction;
    thấy lại trong ngày thì ghi đè bằng số mới nhất.
    """
    unique: dict[int, GitHubRepo] = {}
    for repo in repos:
        unique.setdefault(repo.github_id, repo)

    outcomes: list[UpsertOutcome] = []
    with transaction.atomic():
        for repo in unique.values():
            fields = _fields_from_github(repo, seen_at=seen_at)
            # create_defaults THAY THẾ defaults khi tạo mới (Django không gộp) → phải gộp tay.
            stored, created = Repository.objects.update_or_create(
                github_id=repo.github_id,
                defaults=fields,
                create_defaults={**fields, "first_seen_at": seen_at},
            )
            outcomes.append(UpsertOutcome(repository=stored, created=created))
        _record_snapshots(outcomes, unique, seen_at=seen_at)
    return outcomes


def baseline_snapshots(*, today: date, window_days: int = 7) -> dict[int, StarPoint]:
    """Mốc star để so với hôm nay, theo `repository_id`.

    Mỗi repo: ảnh chụp CŨ NHẤT trong `[today - window_days, today - 1]`; không có thì ảnh chụp
    MỚI NHẤT trước khoảng đó. Repo chưa có ảnh chụp nào trước hôm nay thì vắng mặt.

    Đọc cả bảng trong một lượt (không truyền danh sách id: SQLite giới hạn số tham số mỗi câu lệnh).
    """
    window_start = today - timedelta(days=window_days)
    rows = (
        StarSnapshot.objects.filter(day__lt=today)
        .order_by("repository_id", "day")
        .values_list("repository_id", "day", "stars")
        .iterator()
    )
    baseline: dict[int, StarPoint] = {}
    # Mỗi repo đến theo ngày tăng dần: ảnh chụp cũ hơn khoảng thì cứ ghi đè (giữ cái mới nhất),
    # còn trong khoảng thì chỉ nhận cái đầu tiên (cũ nhất) và bỏ qua phần còn lại.
    for repository_id, day, stars in rows:
        current = baseline.get(repository_id)
        if day < window_start or current is None or current.day < window_start:
            baseline[repository_id] = StarPoint(day=day, stars=stars)
    return baseline


def prune_snapshots(*, before: date) -> int:
    """Xoá ảnh chụp có ngày trước `before`; trả số dòng đã xoá."""
    deleted, _ = StarSnapshot.objects.filter(day__lt=before).delete()
    return deleted


def _record_snapshots(
    outcomes: list[UpsertOutcome], repos: dict[int, GitHubRepo], *, seen_at: datetime
) -> None:
    day = timezone.localdate(seen_at)
    snapshots = [
        StarSnapshot(
            repository=outcome.repository,
            day=day,
            stars=repos[outcome.repository.github_id].stars,
            captured_at=seen_at,
        )
        for outcome in outcomes
    ]
    StarSnapshot.objects.bulk_create(
        snapshots,
        update_conflicts=True,
        unique_fields=["repository", "day"],
        update_fields=["stars", "captured_at"],
    )


def _fields_from_github(repo: GitHubRepo, *, seen_at: datetime) -> dict[str, object]:
    return {
        "full_name": repo.full_name,
        "html_url": repo.html_url,
        "description": repo.description,
        "language": repo.language,
        "topics": list(repo.topics),
        "stars": repo.stars,
        "forks": repo.forks,
        "open_issues": repo.open_issues,
        "owner_login": repo.owner_login,
        "owner_type": repo.owner_type,
        "license_spdx": repo.license_spdx,
        "is_fork": repo.is_fork,
        "is_archived": repo.is_archived,
        "gh_created_at": repo.created_at,
        "gh_pushed_at": repo.pushed_at,
        "last_seen_at": seen_at,
    }


# --- Hồ sơ chủ repo --------------------------------------------------------------------------


def save_owner_profile(user: GitHubUser, *, fetched_at: datetime) -> OwnerProfile:
    """Ghi hồ sơ chủ repo vừa lấy; đã có (cùng login, không phân biệt hoa thường) thì ghi đè."""
    profile, _ = OwnerProfile.objects.update_or_create(
        login=user.login.lower(),
        defaults={
            "github_id": user.github_id,
            "account_type": user.account_type,
            "gh_created_at": user.created_at,
            "followers": user.followers,
            "public_repos": user.public_repos,
            "is_missing": False,
            "fetched_at": fetched_at,
        },
    )
    return profile


def mark_owner_missing(login: str, *, fetched_at: datetime) -> OwnerProfile:
    """GitHub báo tài khoản không còn (404): ghi lại để không gọi nữa, xoá số liệu cũ nếu có."""
    profile, _ = OwnerProfile.objects.update_or_create(
        login=login.lower(),
        defaults={
            "github_id": None,
            "account_type": "",
            "gh_created_at": None,
            "followers": None,
            "public_repos": None,
            "is_missing": True,
            "fetched_at": fetched_at,
        },
    )
    return profile


def owner_profiles_for(logins: Iterable[str]) -> dict[str, OwnerProfile]:
    """Hồ sơ đã lưu của các chủ repo, khoá là login viết thường. Chủ chưa có hồ sơ thì vắng mặt."""
    wanted = sorted({login.lower() for login in logins})
    found: dict[str, OwnerProfile] = {}
    for start in range(0, len(wanted), _IN_BATCH):
        batch = wanted[start : start + _IN_BATCH]
        found.update((p.login, p) for p in OwnerProfile.objects.filter(login__in=batch))
    return found


def logins_needing_profile(logins: Sequence[str], *, fresh_after: datetime) -> list[str]:
    """Các chủ chưa có hồ sơ, hoặc hồ sơ lấy trước `fresh_after` — giữ thứ tự, mỗi chủ một lần."""
    profiles = owner_profiles_for(logins)
    needed: list[str] = []
    seen: set[str] = set()
    for login in logins:
        key = login.lower()
        if key in seen:
            continue
        seen.add(key)
        profile = profiles.get(key)
        if profile is None or profile.fetched_at < fresh_after:
            needed.append(login)
    return needed
