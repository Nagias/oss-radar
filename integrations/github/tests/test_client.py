"""Client GitHub: đọc đúng dữ liệu thật, gửi đúng tham số, biến mọi kiểu hỏng thành lỗi có tên.

Dữ liệu trong tests/fixtures/github/ là phản hồi THẬT của GitHub (rút gọn trường), không tự bịa.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from pytest_django.fixtures import Settings

from integrations.github.client import GitHubClient, get_github_client
from integrations.github.errors import (
    GitHubAuthError,
    GitHubQueryError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubUnavailableError,
)
from integrations.github.pacing import CallBudget, CallBudgetExhaustedError, RequestPacer
from tests.factories import load_fixture as _load
from tests.fakes import FakeTime

API_URL = "https://api.github.com"
SEARCH_URL = f"{API_URL}/search/repositories"


def load_fixture(name: str) -> dict[str, Any]:
    return _load(f"github/{name}")


def make_client(
    clock: FakeTime, *, token: str = "test-token", budget: CallBudget | None = None
) -> GitHubClient:
    pacer = RequestPacer(
        min_interval=0.0,
        sleep=clock.sleep,
        clock=clock.monotonic,
        wall_clock=clock.time,
        jitter=lambda: 0.0,
    )
    return GitHubClient(
        token=token, api_url=API_URL, timeout_seconds=5.0, pacer=pacer, budget=budget
    )


@pytest.fixture
def client(fake_time: FakeTime) -> Iterator[GitHubClient]:
    with make_client(fake_time) as github:
        yield github


# --- Đọc phản hồi thành công -------------------------------------------------------------


def test_search_parses_real_response(client: GitHubClient, http_mock: respx.MockRouter) -> None:
    http_mock.get(SEARCH_URL).respond(json=load_fixture("search_repositories.json"))

    page = client.search_repositories("topic:ai-agent")

    assert page.total_count == 40194
    assert page.incomplete_results is False
    assert [repo.full_name for repo in page.items] == [
        "NousResearch/hermes-agent",
        "Panniantong/Agent-Reach",
        "shareAI-lab/learn-claude-code",
    ]
    first = page.items[0]
    assert first.github_id == 1024554267
    assert first.stars == 255793
    assert first.owner_login == "NousResearch"
    assert first.owner_type == "Organization"
    assert first.language == "Python"
    assert first.license_spdx == "MIT"
    assert first.is_fork is False
    assert first.is_archived is False
    assert first.html_url == "https://github.com/NousResearch/hermes-agent"
    assert first.pushed_at == datetime(2026, 10, 21, 15, 56, 55, tzinfo=UTC)
    assert first.created_at.tzinfo is not None


def test_search_sends_query_sorted_by_stars_with_token(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    route = http_mock.get(SEARCH_URL).respond(json=load_fixture("search_repositories.json"))

    client.search_repositories("topic:ai-agent stars:<1000", per_page=50, page=2)

    request = route.calls.last.request
    assert request.url.params["q"] == "topic:ai-agent stars:<1000"
    assert request.url.params["sort"] == "stars"
    assert request.url.params["order"] == "desc"
    assert request.url.params["per_page"] == "50"
    assert request.url.params["page"] == "2"
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_search_without_token_sends_no_authorization_header(
    http_mock: respx.MockRouter, fake_time: FakeTime
) -> None:
    route = http_mock.get(SEARCH_URL).respond(json=load_fixture("search_repositories.json"))

    with make_client(fake_time, token="") as anonymous:
        anonymous.search_repositories("topic:ai-agent")

    assert "Authorization" not in route.calls.last.request.headers


def test_search_accepts_missing_optional_fields(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    payload = load_fixture("search_repositories.json")
    payload["items"][0].update(description=None, language=None, license=None, pushed_at=None)
    http_mock.get(SEARCH_URL).respond(json=payload)

    repo = client.search_repositories("topic:ai-agent").items[0]

    assert repo.description == ""
    assert repo.language == ""
    assert repo.license_spdx == ""
    assert repo.pushed_at is None


# --- Kiểm tra đầu vào trước khi tốn một lần gọi API -----------------------------------------


@pytest.mark.parametrize("per_page", [0, 101])
def test_search_rejects_page_size_outside_github_limit(client: GitHubClient, per_page: int) -> None:
    with pytest.raises(ValueError, match="per_page"):
        client.search_repositories("topic:ai-agent", per_page=per_page)


@pytest.mark.parametrize("query", ["", "   "])
def test_search_rejects_blank_query(client: GitHubClient, query: str) -> None:
    with pytest.raises(ValueError, match="query"):
        client.search_repositories(query)


# --- Lỗi từ GitHub thành lỗi có tên -----------------------------------------------------------


def test_validation_failed_raises_query_error(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    http_mock.get(SEARCH_URL).respond(422, json=load_fixture("search_validation_failed.json"))

    with pytest.raises(GitHubQueryError, match="Validation Failed"):
        client.search_repositories("topic:ai-agent")


def test_rate_limit_wait_too_long_raises(
    client: GitHubClient, http_mock: respx.MockRouter, fake_time: FakeTime
) -> None:
    reset_epoch = int(fake_time.time()) + 600  # quá 5 phút chờ cho phép
    http_mock.get(SEARCH_URL).respond(
        403,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset_epoch)},
        json={"message": "API rate limit exceeded"},
    )

    with pytest.raises(GitHubRateLimitError) as caught:
        client.search_repositories("topic:ai-agent")

    assert caught.value.reset_at == datetime.fromtimestamp(reset_epoch, tz=UTC)


def test_rate_limited_then_succeeds_after_waiting(
    client: GitHubClient, http_mock: respx.MockRouter, fake_time: FakeTime
) -> None:
    reset_epoch = int(fake_time.time()) + 30
    limited = httpx.Response(
        403,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset_epoch)},
        json={"message": "API rate limit exceeded"},
    )
    ok = httpx.Response(200, json=load_fixture("search_repositories.json"))
    route = http_mock.get(SEARCH_URL).mock(side_effect=[limited, ok])

    page = client.search_repositories("topic:ai-agent")

    assert page.total_count == 40194
    assert route.call_count == 2
    assert fake_time.sleeps == [pytest.approx(31, abs=1)]


def test_too_many_requests_raises_rate_limit_error(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    route = http_mock.get(SEARCH_URL).respond(
        429, headers={"retry-after": "60"}, json={"message": "secondary rate limit"}
    )

    with pytest.raises(GitHubRateLimitError) as caught:
        client.search_repositories("topic:ai-agent")

    assert caught.value.reset_at is None
    assert route.call_count == 4  # 1 lượt đầu + chờ và gọi lại tối đa 3 lần


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_raise_auth_error(
    client: GitHubClient, http_mock: respx.MockRouter, status: int
) -> None:
    http_mock.get(SEARCH_URL).respond(status, json={"message": "Bad credentials"})

    with pytest.raises(GitHubAuthError, match="Bad credentials"):
        client.search_repositories("topic:ai-agent")


def test_server_error_retried_three_times_then_raises(
    client: GitHubClient, http_mock: respx.MockRouter, fake_time: FakeTime
) -> None:
    route = http_mock.get(SEARCH_URL).respond(502, text="Bad Gateway")

    with pytest.raises(GitHubUnavailableError):
        client.search_repositories("topic:ai-agent")

    assert route.call_count == 4
    assert fake_time.sleeps == [2.0, 4.0, 8.0]


def test_transient_error_then_success_returns_page(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    route = http_mock.get(SEARCH_URL).mock(
        side_effect=[
            httpx.ConnectError("mất mạng chốc lát"),
            httpx.Response(200, json=load_fixture("search_repositories.json")),
        ]
    )

    assert client.search_repositories("topic:ai-agent").total_count == 40194
    assert route.call_count == 2


def test_every_attempt_spends_budget(http_mock: respx.MockRouter, fake_time: FakeTime) -> None:
    route = http_mock.get(SEARCH_URL).respond(502, text="Bad Gateway")
    budget = CallBudget(2)

    with make_client(fake_time, budget=budget) as github, pytest.raises(CallBudgetExhaustedError):
        github.search_repositories("topic:ai-agent")

    assert route.call_count == 2
    assert budget.used == 2


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError("không kết nối được"), httpx.ReadTimeout("hết giờ")]
)
def test_network_failure_raises_unavailable_error(
    client: GitHubClient, http_mock: respx.MockRouter, failure: httpx.HTTPError
) -> None:
    route = http_mock.get(SEARCH_URL).mock(side_effect=failure)

    with pytest.raises(GitHubUnavailableError):
        client.search_repositories("topic:ai-agent")

    assert route.call_count == 4


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, text="<html>không phải JSON</html>"),
        httpx.Response(200, json={"total_count": 1, "incomplete_results": False, "items": [{}]}),
    ],
)
def test_malformed_payload_raises_response_error(
    client: GitHubClient, http_mock: respx.MockRouter, response: httpx.Response
) -> None:
    http_mock.get(SEARCH_URL).mock(return_value=response)

    with pytest.raises(GitHubResponseError):
        client.search_repositories("topic:ai-agent")


# --- Tạo client từ cấu hình dự án -------------------------------------------------------------


def test_get_github_client_reads_project_settings(
    settings: Settings, http_mock: respx.MockRouter
) -> None:
    settings.GITHUB_TOKEN = "token-tu-cau-hinh"
    settings.GITHUB_API_URL = "https://github.example.test/api"
    route = http_mock.get("https://github.example.test/api/search/repositories").respond(
        json=load_fixture("search_repositories.json")
    )

    with get_github_client() as github:
        github.search_repositories("topic:ai-agent")

    assert route.calls.last.request.headers["Authorization"] == "Bearer token-tu-cau-hinh"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("id", "1024554267"),  # số bị gửi thành chuỗi
        ("id", True),  # true/false không phải số
        ("fork", "false"),  # chuỗi thay vì true/false
        ("full_name", None),  # thiếu tên
        ("topics", "ai,agent"),  # chuỗi thay vì mảng
        ("owner", "NousResearch"),  # chuỗi thay vì object
        ("created_at", "2026-10-21T15:56:55"),  # thời điểm thiếu múi giờ
    ],
)
def test_wrong_field_type_raises_response_error(
    client: GitHubClient, http_mock: respx.MockRouter, field: str, bad_value: object
) -> None:
    payload = load_fixture("search_repositories.json")
    payload["items"][0][field] = bad_value
    http_mock.get(SEARCH_URL).respond(json=payload)

    with pytest.raises(GitHubResponseError):
        client.search_repositories("topic:ai-agent")


def test_search_rejects_page_before_first(client: GitHubClient) -> None:
    with pytest.raises(ValueError, match="page"):
        client.search_repositories("topic:ai-agent", page=0)


def test_unexpected_status_raises_response_error(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    http_mock.get(SEARCH_URL).respond(404, json={"message": "Not Found"})

    with pytest.raises(GitHubResponseError, match="404"):
        client.search_repositories("topic:ai-agent")


def test_error_body_without_message_falls_back_to_http_reason(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    http_mock.get(SEARCH_URL).respond(500, json={"error": "khác chuẩn"})

    with pytest.raises(GitHubUnavailableError, match="Internal Server Error"):
        client.search_repositories("topic:ai-agent")
