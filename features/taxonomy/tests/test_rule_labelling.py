"""Ghi nhãn do luật gắn (gói 1b của bộ luật): nguồn nhãn, không ghi đè AI, không ép vào "Khác"."""

from datetime import timedelta

import pytest
from django.utils import timezone

from features.catalog.models import Repository
from features.catalog.services import upsert_repositories
from features.taxonomy import services
from features.taxonomy.keywords import load_keywords
from features.taxonomy.models import ClassifyMiss, ClassifyRun, RepoClassification, RepoLabel
from tests.factories import label_repository, make_github_repo
from tests.fakes import FakeLlm

pytestmark = pytest.mark.django_db

Source = RepoClassification.Source
NEUTRAL = "Recipes for dinner"


def repo_with(
    github_id: int, *, topics: tuple[str, ...], seen_in: timedelta = timedelta(0)
) -> Repository:
    """Repo có tên và mô tả trung tính: chỉ topic quyết định nhãn của luật."""
    github_repo = make_github_repo(
        github_id=github_id,
        full_name=f"someone/project-{github_id}",
        topics=topics,
        description=NEUTRAL,
    )
    upsert_repositories([github_repo], seen_at=timezone.now() + seen_in)
    return Repository.objects.get(github_id=github_id)


def seen_again(github_id: int, *, topics: tuple[str, ...]) -> None:
    """Repo được quét lại SAU lần luật kiểm gần nhất (mốc kiểm lùi 2 giờ, thấy lại 1 giờ trước)."""
    RepoClassification.objects.filter(repository__github_id=github_id).update(
        checked_at=timezone.now() - timedelta(hours=2)
    )
    repo_with(github_id, topics=topics, seen_in=-timedelta(hours=1))


def labels_of(repo: Repository) -> set[tuple[str, str]]:
    return set(RepoLabel.objects.filter(repository=repo).values_list("axis", "code"))


def test_rules_label_a_repo_that_has_no_labels() -> None:
    repo = repo_with(1, topics=("comfyui", "cli"))

    report = services.classify_catalog_by_rules()

    row = RepoClassification.objects.get(repository=repo)
    assert (row.source, row.model, row.prompt_version) == (Source.RULE, "luật", 0)
    assert row.rules_version == load_keywords().version
    assert row.taxonomy_version == services.load_taxonomy().version
    assert row.reason.startswith("Luật: ")
    assert row.checked_at is not None
    assert labels_of(repo) == {
        ("aspects", "image"),
        ("aspects", "devtools"),
        ("audience", "developer"),
        ("audience", "creator"),
    }
    assert (report.examined, report.labelled, report.removed, report.unplaced) == (1, 1, 0, 0)


def test_rules_never_touch_ai_labels() -> None:
    repo = repo_with(1, topics=("comfyui",))
    label_repository(repo, audience=("research",), aspects=("video",))

    report = services.classify_catalog_by_rules()

    row = RepoClassification.objects.get(repository=repo)
    assert (row.source, row.model, row.reason) == (Source.AI, "gemini", "lý do 1")
    assert labels_of(repo) == {("aspects", "video"), ("audience", "research")}
    assert report.examined == 0


def test_repo_the_rules_cannot_place_gets_no_row() -> None:
    repo = repo_with(1, topics=("cooking",))

    report = services.classify_catalog_by_rules()

    assert not RepoClassification.objects.filter(repository=repo).exists()
    assert labels_of(repo) == set()
    assert (report.labelled, report.unplaced) == (0, 1)
    # Vẫn là "chưa phân loại" với trang và với AI.
    assert services.label_counts()[services.UNCLASSIFIED] == 1
    assert services.repositories_needing_labels() == [repo]


def test_unchanged_rule_row_is_not_rewritten() -> None:
    repo = repo_with(1, topics=("comfyui",))
    services.classify_catalog_by_rules()
    first = RepoClassification.objects.get(repository=repo)

    # Repo được quét lại (last_seen_at mới hơn) nhưng nội dung không đổi.
    seen_again(1, topics=("comfyui",))
    report = services.classify_catalog_by_rules()

    again = RepoClassification.objects.get(repository=repo)
    assert again.classified_at == first.classified_at
    assert again.checked_at is not None
    assert first.checked_at is not None
    assert again.checked_at > first.checked_at
    assert (report.examined, report.labelled) == (1, 0)

    # Lần sau nữa không còn gì để xét.
    assert services.classify_catalog_by_rules().examined == 0


def test_rule_row_follows_the_repo_when_its_topics_change() -> None:
    repo = repo_with(1, topics=("comfyui",))
    services.classify_catalog_by_rules()

    seen_again(1, topics=("game-engine",))
    report = services.classify_catalog_by_rules()

    assert labels_of(repo) == {("aspects", "game"), ("audience", "gamedev")}
    assert report.labelled == 1


def test_rule_row_is_removed_when_the_repo_no_longer_matches() -> None:
    repo = repo_with(1, topics=("comfyui",))
    services.classify_catalog_by_rules()

    seen_again(1, topics=("cooking",))
    report = services.classify_catalog_by_rules()

    assert not RepoClassification.objects.filter(repository=repo).exists()
    assert labels_of(repo) == set()
    assert (report.removed, report.unplaced) == (1, 0)


def test_rule_rows_are_redone_when_the_keywords_version_changes() -> None:
    repo = repo_with(1, topics=("comfyui",))
    services.classify_catalog_by_rules()
    RepoClassification.objects.filter(repository=repo).update(rules_version=0)
    RepoLabel.objects.filter(repository=repo).delete()  # như thể bản từ khoá cũ gắn khác đi

    report = services.classify_catalog_by_rules()

    assert RepoClassification.objects.get(repository=repo).rules_version == load_keywords().version
    assert ("aspects", "image") in labels_of(repo)
    assert report.labelled == 1


def test_rules_leave_misses_and_runs_alone() -> None:
    repo = repo_with(1, topics=("comfyui",))
    ClassifyMiss.objects.create(repository=repo, misses=2, last_missed_at=timezone.now())

    services.classify_catalog_by_rules()

    assert ClassifyMiss.objects.filter(repository=repo).exists()
    assert ClassifyRun.objects.count() == 0


def test_progress_callback_is_called_per_batch() -> None:
    for github_id in range(1, 4):
        repo_with(github_id, topics=("comfyui",))
    seen: list[int] = []

    services.classify_catalog_by_rules(batch_size=2, after_batch=seen.append)

    assert seen == [2, 3]


# --- Luật và AI cùng tồn tại -----------------------------------------------------------------


def test_ai_skips_rule_labelled_repos_unless_reclassifying() -> None:
    placed = repo_with(1, topics=("comfyui",))
    unplaced = repo_with(2, topics=("cooking",))
    services.classify_catalog_by_rules()

    assert services.repositories_needing_labels() == [unplaced]
    assert set(services.repositories_needing_labels(reclassify=True)) == {placed, unplaced}


def test_ai_overwriting_a_rule_row_becomes_the_source(fake_llm: FakeLlm) -> None:
    repo = repo_with(1, topics=("comfyui",))
    services.classify_catalog_by_rules()

    services.classify_catalog(budget=5, reclassify=True)

    row = RepoClassification.objects.get(repository=repo)
    assert (row.source, row.rules_version) == (Source.AI, 0)
    assert labels_of(repo) == {("aspects", "devtools"), ("audience", "developer")}
    # Và từ đó luật không đụng vào nữa.
    assert services.classify_catalog_by_rules().examined == 0


def test_compare_only_measures_against_ai_rows() -> None:
    label_repository(repo_with(1, topics=("comfyui",)), aspects=("image",))
    repo_with(2, topics=("comfyui",))
    services.classify_catalog_by_rules()  # repo 2 thành dòng nguồn luật

    comparison = services.compare_rules_with_ai()

    assert comparison.compared == 1
