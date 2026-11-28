"""Lệnh `manage.py classify`: phân loại bù cả kho, in tiến độ, báo lỗi rõ."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from pytest_django.fixtures import Settings

from features.catalog.models import Repository
from features.catalog.services import upsert_repositories
from features.taxonomy import services
from features.taxonomy.models import ClassifyRun, RepoClassification
from features.taxonomy.tests.conftest import make_repos
from tests.factories import label_repository, make_github_repo
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


def test_classify_command_budget_stop_is_not_reported_as_ai_misses(fake_llm: FakeLlm) -> None:
    # Hết ngân sách giữa chừng: repo chưa tới lượt không phải "AI bỏ sót" (đo thật 26/11: lệnh
    # `--budget 1` báo "8.934 repo AI bỏ sót" trong khi sổ bỏ sót trống).
    make_repos(90)

    text = run_command("--budget", "1")

    assert "Xong: 40 repo có nhãn, 50 repo chưa có nhãn — chạy lại lệnh để làm tiếp" in text
    assert "AI bỏ sót" not in text


def test_classify_command_reports_repos_ai_kept_missing(fake_llm: FakeLlm) -> None:
    repos = make_repos(3)
    fake_llm.skip_ids = {repos[0].github_id}  # AI bỏ sót cả lượt đầu lẫn lượt thử lại

    text = run_command()

    assert "Xong: 2 repo có nhãn, 1 repo AI bỏ sót" in text


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
    repos = make_repos(50)
    target = repos[0].github_id
    fake_llm.skip_ids = {target}  # lượt đầu AI bỏ sót một repo (ngẫu nhiên)

    def answer_on_retry(call_number: int) -> None:
        if call_number == 3:
            fake_llm.skip_ids.clear()

    fake_llm.on_call = answer_on_retry

    text = run_command()

    assert "Thử lại 1 repo AI bỏ sót" in text
    assert RepoClassification.objects.count() == 50
    assert [len(ids) for ids in fake_llm.calls] == [40, 10, 1]


@pytest.mark.parametrize("args", [("--limit", "-1"), ("--limit", "0"), ("--budget", "0")])
def test_classify_command_rejects_bad_numbers(fake_llm: FakeLlm, args: tuple[str, str]) -> None:
    make_repos(2)

    with pytest.raises(CommandError, match="từ 1"):
        run_command(*args)


# --- So sánh luật với nhãn AI (gói 1a của bộ luật: chỉ đọc) ------------------------------------


def _repo_with(github_id: int, *, topics: tuple[str, ...]) -> Repository:
    # Tên và mô tả trung tính để chỉ topic quyết định nhãn của luật.
    github_repo = make_github_repo(
        github_id=github_id,
        full_name=f"someone/project-{github_id}",
        topics=topics,
        description="Recipes for dinner",
    )
    upsert_repositories([github_repo], seen_at=timezone.now())
    return Repository.objects.get(github_id=github_id)


def test_compare_rules_prints_agreement_per_group_without_ai_key_or_writes() -> None:
    # Hai repo AI xếp vào "Ảnh", luật bắt được một; một repo AI xếp "Video" mà luật lại xếp "Ảnh".
    label_repository(_repo_with(1, topics=("comfyui",)), audience=("creator",), aspects=("image",))
    label_repository(_repo_with(2, topics=("cooking",)), aspects=("image",))
    label_repository(_repo_with(3, topics=("stable-diffusion",)), aspects=("video",))
    _repo_with(4, topics=("comfyui",))  # chưa có nhãn AI: không tính vào phép so
    before = (RepoClassification.objects.count(), ClassifyRun.objects.count())

    text = run_command("--compare-rules")

    assert "So với nhãn AI của 3 repo" in text
    assert "luật không xếp được 1 repo (33%)" in text
    # Cột: AI gắn · luật gắn · trùng · bắt được · đúng.
    assert _row(text, "image") == ["2", "2", "1", "50%", "50%"]
    assert _row(text, "video") == ["1", "0", "0", "0%", "—"]
    assert (RepoClassification.objects.count(), ClassifyRun.objects.count()) == before


def _row(text: str, code: str) -> list[str]:
    for line in text.splitlines():
        cells = line.split()
        if cells and cells[0] == code:
            return cells[-5:]
    raise AssertionError(f"không thấy dòng của nhóm {code} trong:\n{text}")


# --- Ghi nhãn bằng luật (gói 1b) ---------------------------------------------------------------


def test_rules_flag_labels_without_ai_key() -> None:
    _repo_with(1, topics=("comfyui",))
    _repo_with(2, topics=("cooking",))

    text = run_command("--rules")

    assert "Luật đã xét 2 repo: gắn nhãn 1, gỡ nhãn không còn khớp 0, không xếp được 1." in text
    assert RepoClassification.objects.get().source == RepoClassification.Source.RULE
    assert ClassifyRun.objects.count() == 0
