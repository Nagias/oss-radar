"""Dữ liệu mẫu cho trang Kho repo: repo trong kho, nhãn, điểm lưu sẵn."""

from datetime import UTC, datetime, timedelta

from django.utils import timezone

from features.catalog.models import Repository
from features.catalog.services import upsert_repositories
from features.taxonomy.models import RepoClassification, RepoLabel
from tests.factories import make_github_repo


def add_repo(github_id: int, **changes: object) -> Repository:
    fields: dict[str, object] = {
        "github_id": github_id,
        "full_name": f"chu/repo-{github_id}",
        "html_url": f"https://github.com/chu/repo-{github_id}",
        "description": f"Mô tả repo {github_id}",
        "stars": 100,
        "forks": 20,
        "language": "Python",
        "license_spdx": "MIT",
        "created_at": datetime(2025, 1, 1, tzinfo=UTC),
        "pushed_at": timezone.now() - timedelta(days=3),
    }
    fields.update(changes)
    [outcome] = upsert_repositories([make_github_repo(**fields)], seen_at=timezone.now())
    return outcome.repository


def label(
    repo: Repository, *, audience: tuple[str, ...] = (), aspects: tuple[str, ...] = ()
) -> None:
    RepoClassification.objects.update_or_create(
        repository=repo,
        defaults={
            "reason": f"lý do {repo.github_id}",
            "model": "gemini",
            "prompt_version": 1,
            "taxonomy_version": 1,
            "fingerprint": "x",
            "classified_at": timezone.now(),
        },
    )
    RepoLabel.objects.bulk_create(
        [RepoLabel(repository=repo, axis="audience", code=code) for code in audience]
        + [RepoLabel(repository=repo, axis="aspects", code=code) for code in aspects]
    )
