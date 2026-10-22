"""Dữ liệu và phản hồi GitHub giả lập dùng chung cho test của tính năng Quét."""

import functools

import pytest
import respx

from integrations.github.client import get_github_client
from tests.factories import load_fixture
from tests.fakes import FakeTime

SEARCH_URL = "https://api.github.com/search/repositories"

# Thứ tự star giảm dần trong phản hồi thật đã lưu (tests/fixtures/github/search_repositories.json).
REAL_TOP_REPOS = [
    "NousResearch/hermes-agent",
    "Panniantong/Agent-Reach",
    "shareAI-lab/learn-claude-code",
]


@pytest.fixture(autouse=True)
def _github_client_never_sleeps_for_real(
    monkeypatch: pytest.MonkeyPatch, fake_time: FakeTime
) -> None:
    """Client GitHub trong test giãn nhịp, chờ hồi lượt bằng đồng hồ giả — không phải chờ thật."""
    monkeypatch.setattr(
        "features.discovery.services.get_github_client",
        functools.partial(get_github_client, sleep=fake_time.sleep),
    )


@pytest.fixture
def github_search(http_mock: respx.MockRouter) -> respx.Route:
    """GitHub trả về đúng phản hồi thật đã lưu cho mọi lần tìm kiếm."""
    return http_mock.get(SEARCH_URL).respond(json=load_fixture("github/search_repositories.json"))
