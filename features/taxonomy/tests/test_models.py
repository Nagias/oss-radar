"""Nơi lưu nhãn: một bản ghi phân loại mỗi repo, mỗi nhãn một dòng (lọc HOẶC/VÀ bằng CSDL)."""

import pytest
from django.db import IntegrityError
from django.utils import timezone

from features.catalog.models import Repository
from features.catalog.services import upsert_repositories
from features.taxonomy.models import ClassifyRun, RepoClassification, RepoLabel
from tests.factories import make_github_repo

pytestmark = pytest.mark.django_db


def make_repo(github_id: int) -> Repository:
    [outcome] = upsert_repositories(
        [make_github_repo(github_id=github_id, full_name=f"gia-lap/repo-{github_id}")],
        seen_at=timezone.now(),
    )
    return outcome.repository


def test_classification_and_labels_belong_to_repository() -> None:
    repo = make_repo(1)
    RepoClassification.objects.create(
        repository=repo,
        reason="video AI",
        model="gemini",
        prompt_version=1,
        taxonomy_version=1,
        fingerprint="abc",
        classified_at=timezone.now(),
    )
    RepoLabel.objects.create(repository=repo, axis=RepoLabel.Axis.ASPECTS, code="video")

    stored = RepoClassification.objects.get(repository=repo)
    assert stored.reason == "video AI"
    assert str(stored) == "gia-lap/repo-1"
    assert list(RepoLabel.objects.filter(repository=repo).values_list("code", flat=True)) == [
        "video"
    ]


def test_same_label_cannot_be_stored_twice() -> None:
    repo = make_repo(2)
    RepoLabel.objects.create(repository=repo, axis=RepoLabel.Axis.AUDIENCE, code="creator")

    with pytest.raises(IntegrityError):
        RepoLabel.objects.create(repository=repo, axis=RepoLabel.Axis.AUDIENCE, code="creator")


def test_classify_run_defaults() -> None:
    run = ClassifyRun.objects.create(origin=ClassifyRun.Origin.COMMAND)

    assert run.status == ClassifyRun.Status.RUNNING
    counters = (run.calls_used, run.prompt_tokens, run.completion_tokens, run.classified_count)
    assert counters == (0, 0, 0, 0)
    assert run.started_at is not None
