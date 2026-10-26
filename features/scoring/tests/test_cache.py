"""Điểm lưu sẵn (QĐ-19): để lọc và sắp cả kho nhanh; luôn khớp điểm tính trực tiếp."""

from datetime import UTC, datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from features.catalog.models import Repository
from features.catalog.services import upsert_repositories
from features.scoring import services
from features.scoring.models import ScoreCache
from features.scoring.rules import FORMULA_VERSION
from tests.factories import make_github_repo

pytestmark = pytest.mark.django_db

CREATED = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)


def store(github_id: int, **changes: object) -> Repository:
    fields: dict[str, object] = {"github_id": github_id, "full_name": f"chu/repo-{github_id}"}
    fields.update(changes)
    [outcome] = upsert_repositories([make_github_repo(**fields)], seen_at=timezone.now())
    return outcome.repository


def test_refresh_stores_scores_equal_to_live_scores() -> None:
    risky = store(1, stars=613, forks=2, created_at=CREATED, pushed_at=CREATED)
    clean = store(2, stars=1000, forks=100)

    written = services.refresh_scores()

    assert written == 2
    live = services.score_repositories([risky, clean])
    for repo in (risky, clean):
        cached = ScoreCache.objects.get(repository=repo)
        assert cached.quality == live[repo.pk].quality.total
        assert cached.suspicion_points == live[repo.pk].suspicion.points
        assert cached.suspicion_level == live[repo.pk].suspicion.level
        assert cached.formula_version == FORMULA_VERSION
    assert ScoreCache.objects.get(repository=risky).suspicion_level == "high"


def test_refresh_again_overwrites_without_duplicates() -> None:
    repo = store(3, stars=100)
    services.refresh_scores()
    Repository.objects.filter(pk=repo.pk).update(stars=50_000)

    services.refresh_scores()

    assert ScoreCache.objects.count() == 1
    assert ScoreCache.objects.get().quality > 0


def test_refresh_only_given_repositories() -> None:
    first = store(4)
    store(5)

    written = services.refresh_scores(Repository.objects.filter(pk=first.pk))

    assert written == 1
    assert list(ScoreCache.objects.values_list("repository_id", flat=True)) == [first.pk]


def test_refresh_handles_more_rows_than_one_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "REFRESH_BATCH", 3)
    for github_id in range(10, 18):
        store(github_id)

    assert services.refresh_scores() == 8
    assert ScoreCache.objects.count() == 8


def test_rescore_command_reports_count() -> None:
    store(20)
    out = StringIO()

    call_command("rescore", stdout=out)

    assert "Đã tính lại điểm cho 1 repo." in out.getvalue()
