"""Hạ tầng test của tính năng Quét: GitHub giả lập, đồng hồ giả, chạy nền tại chỗ."""

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import replace
from typing import Any

import pytest
import respx

from features.discovery import services
from features.discovery.models import ScanRun
from tests.factories import load_fixture
from tests.fakes import FakeGitHubSearch, FakeTime

SEARCH_URL = "https://api.github.com/search/repositories"

# Thứ tự star giảm dần trong phản hồi thật đã lưu (tests/fixtures/github/search_repositories.json).
REAL_TOP_REPOS = [
    "NousResearch/hermes-agent",
    "Panniantong/Agent-Reach",
    "shareAI-lab/learn-claude-code",
]

DEFAULT_REQUEST = services.ScanRequest(
    query="topic:ai-agent",
    min_stars=0,
    max_stars=None,
    created_from=None,
    created_to=None,
    budget=1,
)


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch, fake_time: FakeTime) -> None:
    """Mọi chỗ chờ (giãn nhịp, chờ hồi lượt, nghỉ khi lỗi) dùng đồng hồ giả — test chạy tức thì."""
    monkeypatch.setattr("time.sleep", fake_time.sleep)


@pytest.fixture(autouse=True)
def _inline_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """Việc nền chạy ngay tại chỗ để test thấy kết quả liền; lỗi bất ngờ nổ thẳng ra test.

    Luồng nền mặc định rảnh; test cần "đang bận" thì tự monkeypatch `core.background.busy_label`.
    """

    def run_now(job: Callable[[int], None], arg: int, *, label: str = "") -> Future[None]:
        job(arg)
        done: Future[None] = Future()
        done.set_result(None)
        return done

    monkeypatch.setattr("core.background.submit", run_now)
    monkeypatch.setattr("core.background.submit_if_idle", run_now)
    monkeypatch.setattr("core.background.busy_label", lambda: None)


@pytest.fixture
def github_search(http_mock: respx.MockRouter) -> respx.Route:
    """GitHub trả về đúng phản hồi thật đã lưu cho mọi lần tìm kiếm."""
    return http_mock.get(SEARCH_URL).respond(json=load_fixture("github/search_repositories.json"))


@pytest.fixture
def use_fake_github(
    http_mock: respx.MockRouter,
) -> Callable[[list[dict[str, Any]]], FakeGitHubSearch]:
    """Gắn một GitHub giả hiểu truy vấn (lọc star, ngày tạo, phân trang) vào http_mock."""

    def attach(items: list[dict[str, Any]]) -> FakeGitHubSearch:
        fake = FakeGitHubSearch(items)
        http_mock.get(SEARCH_URL).mock(side_effect=fake)
        return fake

    return attach


def run_scan_now(**overrides: Any) -> ScanRun:
    """Bắt đầu một lần quét và chạy nó tới khi dừng; mặc định là mức Nhanh (1 lượt gọi)."""
    scan = services.start_scan(replace(DEFAULT_REQUEST, **overrides))
    services.execute_scan(scan.pk)
    scan.refresh_from_db()
    return scan
