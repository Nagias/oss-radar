"""Nghiệp vụ của kho repo. Tính năng khác muốn ghi bảng Repository phải đi qua đây."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from features.catalog.models import Repository
from integrations.github.schemas import GitHubRepo


@dataclass(frozen=True, slots=True)
class UpsertOutcome:
    repository: Repository
    created: bool


def upsert_repositories(repos: Iterable[GitHubRepo], *, seen_at: datetime) -> list[UpsertOutcome]:
    """Ghi repo vào kho: repo mới thì thêm, repo đã có (cùng github_id) thì cập nhật số liệu.

    Repo lặp lại trong cùng một lô chỉ được tính một lần. Trả về kết quả theo thứ tự đầu vào.
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
    return outcomes


def _fields_from_github(repo: GitHubRepo, *, seen_at: datetime) -> dict[str, object]:
    return {
        "full_name": repo.full_name,
        "html_url": repo.html_url,
        "description": repo.description,
        "language": repo.language,
        "topics": list(repo.topics),
        "stars": repo.stars,
        "forks": repo.forks,
        "owner_login": repo.owner_login,
        "owner_type": repo.owner_type,
        "license_spdx": repo.license_spdx,
        "is_fork": repo.is_fork,
        "is_archived": repo.is_archived,
        "gh_created_at": repo.created_at,
        "gh_pushed_at": repo.pushed_at,
        "last_seen_at": seen_at,
    }
