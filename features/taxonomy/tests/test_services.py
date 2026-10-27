"""Dịch vụ phân loại: gom lô, lưu ngay, không gọi lại repo không đổi, hỏng không mất phần cũ."""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from features.catalog.models import Repository
from features.taxonomy import services
from features.taxonomy.models import (
    ClassifyMiss,
    ClassifyRun,
    RepoClassification,
    RepoLabel,
)
from features.taxonomy.prompt import PROMPT_VERSION
from features.taxonomy.tests.conftest import make_repos
from integrations.github.pacing import CallBudget, CallBudgetExhaustedError
from integrations.llm.client import get_llm_client
from integrations.llm.errors import LlmAuthError
from tests.fakes import FakeLlm, FakeTime

pytestmark = pytest.mark.django_db

Origin = ClassifyRun.Origin
Status = ClassifyRun.Status


def classify_all(
    budget: int = 100, **kwargs: object
) -> tuple[ClassifyRun, services.ClassifyOutcome]:
    run = services.start_classify_run(Origin.COMMAND)
    repos = services.repositories_needing_labels(**kwargs)  # type: ignore[arg-type]
    with get_llm_client(budget=CallBudget(budget)) as llm:
        outcome = services.classify(run, repos, llm=llm)
    services.finish_classify_run(run)
    run.refresh_from_db()
    return run, outcome


def test_classifies_in_batches_of_40_and_stores_labels(fake_llm: FakeLlm) -> None:
    repos = make_repos(90)
    fake_llm.labels = lambda repo_id: (
        (["creator"], ["video", "audio"]) if repo_id % 2 else (["developer"], ["devtools"])
    )

    run, outcome = classify_all()

    assert [len(ids) for ids in fake_llm.calls] == [40, 40, 10]
    assert fake_llm.calls[0][0] == repos[0].github_id  # nhiều star trước
    assert (outcome.classified, outcome.missing, outcome.calls) == (90, 0, 3)
    assert (run.status, run.calls_used, run.classified_count) == (Status.DONE, 3, 90)
    assert (run.prompt_tokens, run.completion_tokens) == (3 * 2285, 3 * 137)
    odd = repos[0] if repos[0].github_id % 2 else repos[1]
    labels = services.labels_for([odd.pk])[odd.pk]
    assert [c.code for c in labels.audience] == ["creator"]
    assert [c.name for c in labels.aspects] == ["Video & làm phim AI", "Âm thanh & giọng nói"]
    assert labels.reason == f"từ khoá của repo {odd.github_id}"
    stored = RepoClassification.objects.get(repository=odd)
    assert (stored.prompt_version, stored.taxonomy_version) == (PROMPT_VERSION, 1)
    assert stored.model == "gemini-3.8-flash-n"


def test_second_pass_calls_nothing_and_changed_repo_is_redone(fake_llm: FakeLlm) -> None:
    repos = make_repos(5)
    classify_all()

    _, again = classify_all()
    assert again.calls == 0
    # Quét lại thấy mô tả mới (upsert ghi cả last_seen_at).
    Repository.objects.filter(pk=repos[2].pk).update(
        description="Mô tả mới hẳn", last_seen_at=timezone.now() + timedelta(minutes=1)
    )
    fake_llm.labels = lambda _id: (["marketer"], ["ads"])

    _, redo = classify_all()

    assert fake_llm.calls[-1] == [repos[2].github_id]
    assert redo.classified == 1
    codes = RepoLabel.objects.filter(repository=repos[2]).values_list("code", flat=True)
    assert sorted(codes) == ["ads", "marketer"]  # nhãn cũ bị thay, không cộng dồn


def test_reclassify_redoes_repos_labelled_by_old_versions(fake_llm: FakeLlm) -> None:
    make_repos(3)
    classify_all()
    RepoClassification.objects.update(taxonomy_version=0)

    assert services.repositories_needing_labels() == []
    _, outcome = classify_all(reclassify=True)

    assert outcome.classified == 3


def test_missing_repo_in_reply_stays_unlabelled(fake_llm: FakeLlm) -> None:
    repos = make_repos(3)
    fake_llm.skip_ids = {repos[1].github_id}

    _, outcome = classify_all()

    assert (outcome.classified, outcome.missing) == (2, 1)
    assert services.repositories_needing_labels() == [repos[1]]


def test_garbled_batch_is_split_and_retried(fake_llm: FakeLlm) -> None:
    make_repos(50)
    fake_llm.garbled = {1}  # lô 40 đầu tiên AI trả lời hỏng (ngẫu nhiên, ~2% lô)

    run, outcome = classify_all()

    assert [len(ids) for ids in fake_llm.calls] == [40, 20, 20, 10]
    assert (outcome.classified, outcome.missing, outcome.calls) == (50, 0, 4)
    assert "không phải JSON" in run.error


def test_budget_runs_out_keeping_batches_already_saved(fake_llm: FakeLlm) -> None:
    make_repos(90)
    run = services.start_classify_run(Origin.COMMAND)
    repos = services.repositories_needing_labels()

    with get_llm_client(budget=CallBudget(2)) as llm, pytest.raises(CallBudgetExhaustedError):
        services.classify(run, repos, llm=llm)

    assert RepoClassification.objects.count() == 80
    run.refresh_from_db()
    assert run.calls_used == 2


def test_rejected_key_raises_after_nothing_saved(fake_llm: FakeLlm) -> None:
    make_repos(3)
    fake_llm.fail_with = lambda _n: 401
    run = services.start_classify_run(Origin.COMMAND)

    with get_llm_client() as llm, pytest.raises(LlmAuthError):
        services.classify(run, services.repositories_needing_labels(), llm=llm)
    services.finish_classify_run(run, error="9router từ chối khoá")

    run.refresh_from_db()
    assert (run.status, run.calls_used) == (Status.FAILED, 1)
    assert RepoClassification.objects.count() == 0


def test_before_each_runs_before_every_batch(fake_llm: FakeLlm) -> None:
    make_repos(50)
    seen: list[int] = []
    run = services.start_classify_run(Origin.COMMAND)

    with get_llm_client() as llm:
        services.classify(
            run,
            services.repositories_needing_labels(),
            llm=llm,
            before_each=lambda: seen.append(len(fake_llm.calls)),
        )

    assert seen == [0, 1]


def test_second_live_run_is_refused_and_stale_one_is_closed() -> None:
    first = services.start_classify_run(Origin.BACKLOG)

    with pytest.raises(services.ClassifyBusyError) as busy:
        services.start_classify_run(Origin.COMMAND)
    assert busy.value.run == first

    ClassifyRun.objects.filter(pk=first.pk).update(
        heartbeat_at=timezone.now() - timedelta(minutes=11)
    )
    second = services.start_classify_run(Origin.COMMAND)

    first.refresh_from_db()
    assert (first.status, first.error) == (Status.FAILED, "Bị gián đoạn (app tắt giữa chừng).")
    assert second.status == Status.RUNNING


def test_labels_for_skips_codes_no_longer_in_taxonomy(fake_llm: FakeLlm) -> None:
    [repo] = make_repos(1)
    classify_all()
    RepoLabel.objects.create(repository=repo, axis=RepoLabel.Axis.ASPECTS, code="da_bo")

    labels = services.labels_for([repo.pk])

    assert [c.code for c in labels[repo.pk].aspects] == ["devtools"]
    assert services.labels_for([]) == {}


def test_labels_for_handles_long_id_lists(fake_llm: FakeLlm) -> None:
    repos = make_repos(3)
    classify_all()

    labels = services.labels_for([repo.pk for repo in repos] + list(range(10_000, 11_200)))

    assert set(labels) == {repo.pk for repo in repos}


def test_label_counts_include_unclassified(fake_llm: FakeLlm) -> None:
    make_repos(3)
    classify_all()
    make_repos(2, start=100)

    counts = services.label_counts()

    assert counts["developer"] == 3
    assert counts["devtools"] == 3
    assert counts[services.UNCLASSIFIED] == 2


def test_ai_calls_on_counts_by_day_and_origin(fake_llm: FakeLlm) -> None:
    make_repos(45)
    classify_all()
    yesterday = ClassifyRun.objects.create(origin=Origin.COMMAND, calls_used=9)
    ClassifyRun.objects.filter(pk=yesterday.pk).update(
        started_at=timezone.now() - timedelta(days=1)
    )

    assert services.ai_calls_on(timezone.localdate(), origin=Origin.COMMAND) == 2
    assert services.ai_calls_on(timezone.localdate(), origin=Origin.BACKLOG) == 0


def test_only_unlabelled_or_reseen_repos_are_examined(
    fake_llm: FakeLlm, django_assert_max_num_queries: Any
) -> None:
    repos = make_repos(3)
    classify_all()
    # Mô tả đổi nhưng repo chưa được quét lại (last_seen_at cũ hơn lúc phân loại): không thể xảy ra
    # ngoài đời — chỉ upsert khi quét mới đổi mô tả. Dùng để chứng minh repo này không được xét lại.
    Repository.objects.filter(pk=repos[0].pk).update(description="đổi mà không quét lại")
    Repository.objects.filter(pk=repos[1].pk).update(
        description="quét lại thấy mô tả mới", last_seen_at=timezone.now() + timedelta(minutes=1)
    )

    with django_assert_max_num_queries(2):
        needed = services.repositories_needing_labels()

    assert needed == [repos[1]]


# --- Lô bị từ chối, repo AI không phân loại được, nhịp sống lúc chờ (rà soát F-010) -------------


def test_refused_batch_is_split_until_the_bad_repo_is_isolated(
    fake_llm: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "BATCH_SIZE", 4)
    repos = make_repos(4)
    bad = repos[3].github_id
    fake_llm.fail_when_ids = lambda ids: 400 if bad in ids else None  # bộ lọc an toàn chặn

    run, outcome = classify_all()

    assert fake_llm.calls == [
        [r.github_id for r in repos],
        [repos[0].github_id, repos[1].github_id],
        [repos[2].github_id, bad],
        [repos[2].github_id],
        [bad],
    ]
    assert (outcome.classified, outcome.missing, outcome.calls) == (3, 1, 5)
    assert run.status == Status.DONE
    assert "nội dung bị chặn" in run.error
    miss = ClassifyMiss.objects.get()
    assert (miss.repository_id, miss.misses) == (repos[3].pk, 1)


def test_repo_missed_twice_rests_seven_days(fake_llm: FakeLlm) -> None:
    repos = make_repos(3)
    fake_llm.skip_ids = {repos[1].github_id}
    classify_all()
    classify_all()

    assert services.repositories_needing_labels() == []  # nghỉ, không đốt lượt mỗi nhịp
    assert [r.pk for r in services.repositories_needing_labels(reclassify=True)] == [repos[1].pk]
    ClassifyMiss.objects.update(last_missed_at=timezone.now() - timedelta(days=8))
    assert services.repositories_needing_labels() == [repos[1]]


def test_success_clears_previous_misses(fake_llm: FakeLlm) -> None:
    [repo] = make_repos(1)
    fake_llm.skip_ids = {repo.github_id}
    classify_all()
    fake_llm.skip_ids = set()

    classify_all()

    assert ClassifyMiss.objects.count() == 0
    assert RepoClassification.objects.filter(repository=repo).exists()


def test_reseen_but_unchanged_repo_is_checked_once(fake_llm: FakeLlm) -> None:
    [repo] = make_repos(1)
    classify_all()
    an_hour_ago = timezone.now() - timedelta(hours=1)
    RepoClassification.objects.update(checked_at=an_hour_ago)
    # Quét lại nửa giờ trước, mô tả không đổi.
    Repository.objects.filter(pk=repo.pk).update(last_seen_at=an_hour_ago + timedelta(minutes=30))

    assert services.repositories_needing_labels() == []

    stored = RepoClassification.objects.get(repository=repo)
    assert stored.checked_at is not None
    repo.refresh_from_db()
    assert stored.checked_at >= repo.last_seen_at  # lần sau không phải kiểm lại


def test_heartbeat_sleep_beats_run_while_waiting(fake_llm: FakeLlm, fake_time: FakeTime) -> None:
    run = services.start_classify_run(Origin.BACKLOG)
    ClassifyRun.objects.filter(pk=run.pk).update(heartbeat_at=timezone.now() - timedelta(minutes=9))
    beats: list[int] = []

    sleep = services.heartbeat_sleep(run, also=lambda: beats.append(1))
    sleep(25)

    assert fake_time.sleeps == [10, 10, 5]
    assert len(beats) == 3
    run.refresh_from_db()
    assert run.heartbeat_at > timezone.now() - timedelta(minutes=1)


def test_classify_catalog_retries_missed_once_and_reports(fake_llm: FakeLlm) -> None:
    make_repos(50)
    fake_llm.garbled = {1}  # lượt đầu AI trả lời hỏng → chia đôi lô 40 → thử lại ngay
    progress: list[tuple[int, int]] = []

    report = services.classify_catalog(budget=100, on_progress=lambda d, t: progress.append((d, t)))

    assert report.needed == 50
    assert report.run is not None
    assert report.run.classified_count == 50
    assert report.stopped == ""
    assert progress[-1] == (50, 50)
