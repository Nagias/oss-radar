"""Dữ liệu và phản hồi GitHub giả lập dùng chung cho test của tính năng Quét."""

import pytest
import respx

from tests.factories import load_fixture

SEARCH_URL = "https://api.github.com/search/repositories"

# Thứ tự star giảm dần trong phản hồi thật đã lưu (tests/fixtures/github/search_repositories.json).
REAL_TOP_REPOS = [
    "NousResearch/hermes-agent",
    "Panniantong/Agent-Reach",
    "shareAI-lab/learn-claude-code",
]


@pytest.fixture
def github_search(http_mock: respx.MockRouter) -> respx.Route:
    """GitHub trả về đúng phản hồi thật đã lưu cho mọi lần tìm kiếm."""
    return http_mock.get(SEARCH_URL).respond(json=load_fixture("github/search_repositories.json"))
