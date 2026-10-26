"""Lệnh `manage.py classify`: phân loại bù cả kho, in tiến độ, báo lỗi rõ."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from pytest_django.fixtures import Settings

from features.taxonomy import services
from features.taxonomy.models import ClassifyRun, RepoClassification
from features.taxonomy.tests.conftest import make_repos
from tests.fakes import FakeLlm

pytestmark = pytest.mark.django_db


def run_command(*args: str) -> str:
    out = StringIO()
    call_command("classify", *args, stdout=out)
    return out.getvalue()


def test_classify_command_prints_progress_and_summary(fake_llm: FakeLlm) -> None:
    make_repos(45)

    text = run_command()

    assert "Cần phân loại: 45 repo" in text
    assert "[40/45]" in text
    assert "[45/45]" in text
    assert "Xong: 45 repo có nhãn, 0 repo AI bỏ sót · 2 lượt gọi AI" in text
    assert "4.570 token vào, 274 token ra" in text
    assert ClassifyRun.objects.get().status == ClassifyRun.Status.DONE


def test_classify_command_respects_budget_and_limit(fake_llm: FakeLlm) -> None:
    make_repos(90)

    text = run_command("--budget", "1")

    assert "Hết ngân sách 1 lượt gọi" in text
    assert RepoClassification.objects.count() == 40

    run_command("--limit", "5")
    assert RepoClassification.objects.count() == 45


def test_classify_command_reclassify(fake_llm: FakeLlm) -> None:
    make_repos(2)
    run_command()
    RepoClassification.objects.update(prompt_version=0)

    assert "Cần phân loại: 0 repo" in run_command()
    assert "Cần phân loại: 2 repo" in run_command("--reclassify")


def test_classify_command_without_key_explains(settings: Settings) -> None:
    settings.LLM_API_KEY = ""

    with pytest.raises(CommandError, match="LLM_API_KEY"):
        run_command()


def test_classify_command_refused_while_another_run_is_live(fake_llm: FakeLlm) -> None:
    make_repos(1)
    services.start_classify_run(ClassifyRun.Origin.BACKLOG)

    with pytest.raises(CommandError, match="Đang phân loại"):
        run_command()


def test_classify_command_reports_rejected_key(fake_llm: FakeLlm) -> None:
    make_repos(2)
    fake_llm.fail_with = lambda _n: 401

    with pytest.raises(CommandError, match="từ chối khoá"):
        run_command()

    assert ClassifyRun.objects.get().status == ClassifyRun.Status.FAILED


def test_classify_command_ctrl_c_closes_run(fake_llm: FakeLlm) -> None:
    make_repos(90)

    def press_ctrl_c(call_number: int) -> None:
        if call_number == 2:
            raise KeyboardInterrupt

    fake_llm.on_call = press_ctrl_c

    with pytest.raises(KeyboardInterrupt):
        run_command()

    run = ClassifyRun.objects.get()
    assert (run.status, run.error) == (ClassifyRun.Status.FAILED, "Dừng tay (Ctrl+C).")
    assert RepoClassification.objects.count() == 40


def test_classify_command_retries_missed_repos_once(fake_llm: FakeLlm) -> None:
    make_repos(50)
    fake_llm.garbled = {1}  # lượt đầu AI trả lời hỏng (đo thật: ~2% lô, ngẫu nhiên)

    text = run_command()

    assert "Thử lại 40 repo AI bỏ sót" in text
    assert RepoClassification.objects.count() == 50
    assert [len(ids) for ids in fake_llm.calls] == [40, 10, 40]
