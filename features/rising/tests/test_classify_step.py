"""Lượt hằng ngày, bước "Phân loại repo" (F-010), và việc nền phân loại dần cả kho.

Bước phân loại chỉ làm giàu dữ liệu: hỏng gì cũng ghi chú rồi lập báo cáo (nguyên tắc 8).
"""

from datetime import timedelta
from typing import Any

import pytest
import respx
from django.utils import timezone
from pytest_django.fixtures import Settings

from features.catalog.services import upsert_repositories
from features.rising import services
from features.rising.models import DailyRun, WatchQuery
from features.rising.tests.conftest import UseFake, days_ago, history, item, snapshot
from features.taxonomy import services as taxonomy
from features.taxonomy.models import ClassifyRun, RepoClassification
from tests.factories import make_github_repo
from tests.fakes import LLM_CHAT_URL, FakeLlm

pytestmark = pytest.mark.django_db

Status = DailyRun.Status
Step = DailyRun.Step
FAST, MID, OTHER = 401, 402, 403


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github


@pytest.fixture
def fake_llm(http_mock: respx.MockRouter, settings: Settings) -> FakeLlm:
    settings.LLM_API_KEY = "khoa-thu"
    settings.LLM_BASE_URL = "http://localhost:20128/v1"
    settings.LLM_MIN_INTERVAL_SECONDS = 0.0
    fake = FakeLlm(labels=lambda _id: (["creator"], ["video"]))
    http_mock.post(LLM_CHAT_URL).mock(side_effect=fake)
    return fake


def three_repos(use_fake: UseFake) -> Any:
    """Rising: OTHER +140, FAST +70. MID +20 là ứng viên không rising."""
    snapshot(FAST, stars=100)
    return use_fake(
        [
            item(FAST, stars=160),
            item(MID, stars=200, created=days_ago(20)),
            item(OTHER, stars=300, created=days_ago(15)),
        ],
        {
            FAST: history(dict.fromkeys(range(30), 10)),
            MID: history({1: 10, 2: 10}),
            OTHER: history(dict.fromkeys(range(7), 20)),
        },
    )


def run_daily_now() -> DailyRun:
    run = services.prepare_daily_run()
    services.execute_daily_run(run.pk)
    run.refresh_from_db()
    return run


def labelled_ids() -> set[int]:
    return set(RepoClassification.objects.values_list("repository__github_id", flat=True))


# --- Bước phân loại trong lượt ----------------------------------------------------------------


def test_daily_run_labels_repos_of_the_run(
    watch_list: list[WatchQuery], use_fake: UseFake, fake_llm: FakeLlm
) -> None:
    three_repos(use_fake)

    run = run_daily_now()

    assert {FAST, MID, OTHER} <= labelled_ids()
    assert run.ai_calls_used == 1
    assert (run.status, run.step, run.problems) == (Status.SUCCEEDED, Step.REPORT, [])
    assert ClassifyRun.objects.get().origin == ClassifyRun.Origin.DAILY


def test_rising_repos_are_labelled_first(
    watch_list: list[WatchQuery],
    use_fake: UseFake,
    fake_llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(taxonomy, "BATCH_SIZE", 1)
    monkeypatch.setattr(services, "DAILY_RUN_CLASSIFY_CALLS", 2)
    three_repos(use_fake)

    run = run_daily_now()

    assert fake_llm.calls == [[OTHER], [FAST]]  # rising, tăng nhiều trước; MID chờ phân loại dần
    assert (run.status, run.problems) == (Status.SUCCEEDED, [])  # hết ngân sách không phải lỗi


@pytest.mark.parametrize("status", [401, 503])
def test_ai_failure_is_noted_and_report_still_made(
    watch_list: list[WatchQuery], use_fake: UseFake, fake_llm: FakeLlm, status: int
) -> None:
    three_repos(use_fake)
    fake_llm.fail_with = lambda _n: status

    run = run_daily_now()

    assert (run.status, run.step) == (Status.SUCCEEDED_PARTIAL, Step.REPORT)
    assert services.latest_report_run() == run
    assert len(run.problems) == 1
    assert run.problems[0].startswith("Phân loại repo bị ngắt")
    assert "3 repo chưa có nhãn" in run.problems[0]
    assert ClassifyRun.objects.get().status == ClassifyRun.Status.FAILED


def test_ai_busy_elsewhere_is_noted(
    watch_list: list[WatchQuery], use_fake: UseFake, fake_llm: FakeLlm
) -> None:
    three_repos(use_fake)
    taxonomy.start_classify_run(ClassifyRun.Origin.COMMAND)  # lệnh classify đang chạy

    run = run_daily_now()

    assert run.status == Status.SUCCEEDED_PARTIAL
    assert "đang có lần phân loại khác" in run.problems[0]
    assert fake_llm.calls == []


def test_stop_during_classification_still_reports(
    watch_list: list[WatchQuery],
    use_fake: UseFake,
    fake_llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(taxonomy, "BATCH_SIZE", 1)
    three_repos(use_fake)

    def press_stop(call_number: int) -> None:
        if call_number == 1:
            services.request_daily_stop(DailyRun.objects.get())

    fake_llm.on_call = press_stop

    run = run_daily_now()

    assert len(fake_llm.calls) == 1
    assert (run.status, run.step, run.stop_requested) == (
        Status.SUCCEEDED_PARTIAL,
        Step.REPORT,
        False,
    )
    assert "bạn bấm Dừng" in run.problems[0]


def test_without_ai_key_the_step_is_skipped_silently(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    three_repos(use_fake)

    run = run_daily_now()

    assert (run.status, run.problems, run.ai_calls_used) == (Status.SUCCEEDED, [], 0)
    assert labelled_ids() == set()


# --- Phân loại dần cả kho ---------------------------------------------------------------------


def catalog_of(count: int) -> None:
    upsert_repositories(
        [
            make_github_repo(github_id=5000 + index, full_name=f"kho/repo-{index}")
            for index in range(count)
        ],
        seen_at=timezone.now(),
    )


def finished_run_today() -> DailyRun:
    return DailyRun.objects.create(
        day=timezone.localdate(), status=Status.SUCCEEDED, step=Step.REPORT
    )


def test_backlog_waits_for_todays_daily_run(fake_llm: FakeLlm) -> None:
    catalog_of(5)

    assert services.classify_backlog_if_due() == 0
    DailyRun.objects.create(day=timezone.localdate(), status=Status.RUNNING, step=Step.RESCAN)
    assert services.classify_backlog_if_due() == 0
    assert fake_llm.calls == []


def test_backlog_classifies_at_most_ten_calls_per_tick(
    fake_llm: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(taxonomy, "BATCH_SIZE", 2)
    catalog_of(30)
    finished_run_today()

    used = services.classify_backlog_if_due()

    assert used == 10
    assert RepoClassification.objects.count() == 20
    run = ClassifyRun.objects.get()
    assert (run.origin, run.status) == (ClassifyRun.Origin.BACKLOG, ClassifyRun.Status.DONE)


def test_backlog_respects_daily_cap(
    fake_llm: FakeLlm, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(taxonomy, "BATCH_SIZE", 1)
    settings.LLM_BACKLOG_CALLS_PER_DAY = 12
    catalog_of(30)
    finished_run_today()

    assert services.classify_backlog_if_due() == 10
    assert services.classify_backlog_if_due() == 2
    assert services.classify_backlog_if_due() == 0


def test_backlog_rests_30_minutes_after_an_error(fake_llm: FakeLlm) -> None:
    catalog_of(5)
    finished_run_today()
    fake_llm.fail_with = lambda _n: 401

    assert services.classify_backlog_if_due() == 1
    failed = ClassifyRun.objects.get()
    assert failed.status == ClassifyRun.Status.FAILED
    assert services.classify_backlog_if_due() == 0  # vừa lỗi: nghỉ

    ClassifyRun.objects.update(finished_at=timezone.now() - timedelta(minutes=31))
    fake_llm.fail_with = None
    assert services.classify_backlog_if_due() == 1


def test_backlog_does_nothing_when_all_labelled_or_no_key(
    fake_llm: FakeLlm, settings: Settings
) -> None:
    finished_run_today()
    assert services.classify_backlog_if_due() == 0  # kho trống
    catalog_of(2)
    settings.LLM_API_KEY = ""
    assert services.classify_backlog_if_due() == 0
    assert fake_llm.calls == []


def test_backlog_is_a_scheduled_job(settings: Settings) -> None:
    assert "features.rising.services.classify_backlog_if_due" in settings.SCHEDULED_JOBS


# --- Trạng thái, ước lượng ---------------------------------------------------------------------


def test_headline_while_classifying() -> None:
    DailyRun.objects.create(
        day=timezone.localdate(),
        status=Status.RUNNING,
        step=Step.CLASSIFY,
        heartbeat_at=timezone.now(),
        ai_calls_used=2,
    )

    assert services.today_status().headline == (
        "Đang chạy: phân loại repo của lượt bằng AI — đã dùng 2 lượt gọi."
    )


def test_estimate_counts_ai_calls_and_step_name() -> None:
    DailyRun.objects.create(
        day=timezone.localdate() - timedelta(days=1),
        status=Status.SUCCEEDED,
        step=Step.REPORT,
        search_calls_used=500,
        verify_calls_used=280,
        owner_calls_used=15,
        ai_calls_used=5,
    )

    assert services.daily_estimate().calls == 800
    assert Step.CLASSIFY.label == "Phân loại repo"
