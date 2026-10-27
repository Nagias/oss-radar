"""Hạ tầng test phân loại: 9router giả, không ngủ thật, repo mẫu."""

from collections.abc import Callable

import pytest
import respx
from django.utils import timezone
from pytest_django.fixtures import Settings

from features.catalog.models import Repository
from features.catalog.services import upsert_repositories
from tests.factories import make_github_repo
from tests.fakes import LLM_CHAT_URL, FakeLlm, FakeTime


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch, fake_time: FakeTime) -> None:
    monkeypatch.setattr("time.sleep", fake_time.sleep)


@pytest.fixture
def fake_llm(http_mock: respx.MockRouter, settings: Settings) -> FakeLlm:
    """9router giả đã gắn, và cấu hình AI như khi đã điền khoá."""
    settings.LLM_API_KEY = "khoa-thu"
    settings.LLM_BASE_URL = "http://localhost:20128/v1"
    settings.LLM_MIN_INTERVAL_SECONDS = 0.0
    fake = FakeLlm()
    http_mock.post(LLM_CHAT_URL).mock(side_effect=fake)
    return fake


MakeRepos = Callable[..., list[Repository]]


def make_repos(count: int, *, start: int = 1, stars: int = 100) -> list[Repository]:
    """`count` repo, repo đầu nhiều star nhất (thứ tự phân loại = star giảm dần)."""
    outcomes = upsert_repositories(
        [
            make_github_repo(
                github_id=start + index,
                full_name=f"chu/repo-{start + index}",
                html_url=f"https://github.com/chu/repo-{start + index}",
                stars=stars + count - index,
                description=f"Mô tả repo {start + index}",
            )
            for index in range(count)
        ],
        seen_at=timezone.now(),
    )
    return [outcome.repository for outcome in outcomes]
