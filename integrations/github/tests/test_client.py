"""Client GitHub: đọc đúng dữ liệu thật, gửi đúng tham số, biến mọi kiểu hỏng thành lỗi có tên.

Dữ liệu trong tests/fixtures/github/ là phản hồi THẬT của GitHub (rút gọn trường), không tự bịa.
"""

import copy
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest
import respx
from pytest_django.fixtures import Settings

from integrations.github.client import GitHubClient, get_github_client
from integrations.github.errors import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubQueryError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubUnavailableError,
)
from integrations.github.pacing import CallBudget, CallBudgetExhaustedError, RequestPacer
from tests.factories import load_fixture as _load
from tests.factories import load_fixture_list as _load_list
from tests.fakes import FakeStarHistory, FakeTime, make_star_history

API_URL = "https://api.github.com"
SEARCH_URL = f"{API_URL}/search/repositories"
HISTORY_URL = f"{API_URL}/repositories/42976210/stargazers/history"


def load_fixture(name: str) -> dict[str, Any]:
    return _load(f"github/{name}")


def load_fixture_list(name: str) -> list[Any]:
    return _load_list(f"github/{name}")


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
    http_mock.get(SEARCH_URL).respond(410, json={"message": "Gone"})

    with pytest.raises(GitHubResponseError, match="410"):
        client.search_repositories("topic:ai-agent")


def test_error_body_without_message_falls_back_to_http_reason(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    http_mock.get(SEARCH_URL).respond(500, json={"error": "khác chuẩn"})

    with pytest.raises(GitHubUnavailableError, match="Internal Server Error"):
        client.search_repositories("topic:ai-agent")


# --- Lịch sử star theo id repo -----------------------------------------------------------------


def test_star_history_parses_real_response(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    http_mock.get(HISTORY_URL).respond(json=load_fixture_list("star_history_old.json"))

    history = client.star_history(42976210)

    assert len(history.weeks) == 6
    assert history.weeks[0].start.weekday() == 6  # Chủ nhật
    assert all(len(week.days) == 7 for week in history.weeks)
    for newer, older in zip(history.weeks, history.weeks[1:], strict=False):
        assert newer.start - older.start == timedelta(days=7)
    assert history.weeks[0].start == datetime.fromtimestamp(1792281600, tz=UTC).date()
    assert history.weeks[0].days == (7, 6, 4, 7, 2, 0, 0)


def test_star_history_of_young_repo_has_fewer_weeks_than_asked(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    # Repo mới tạo: dù xin 6 tuần GitHub chỉ trả những tuần đã có sao.
    young_url = f"{API_URL}/repositories/1416766144/stargazers/history"
    http_mock.get(young_url).respond(json=load_fixture_list("star_history_recent.json"))

    history = client.star_history(1416766144)

    assert [week.days for week in history.weeks] == [
        (4, 8, 6, 6, 2, 0, 0),
        (0, 0, 0, 690, 139, 49, 36),
    ]
    assert history.weeks[0].start - history.weeks[1].start == timedelta(days=7)


def test_star_history_requests_by_github_id_with_per_page(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    route = http_mock.get(HISTORY_URL).respond(json=load_fixture_list("star_history_old.json"))

    client.star_history(42976210)
    assert route.calls.last.request.url.params["per_page"] == "6"

    client.star_history(42976210, weeks=2)
    assert route.calls.last.request.url.params["per_page"] == "2"


def _with_first_week(**changes: Any) -> list[Any]:
    weeks = copy.deepcopy(load_fixture_list("star_history_old.json"))
    weeks[0].update(changes)
    return weeks


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_with_first_week(days=[7, 6, 4, 7, 2, 0], total=26), id="6-so-trong-tuan"),
        pytest.param(
            _with_first_week(days=[8, 6, 4, 7, 2, 0, 0, 1], total=28), id="8-so-trong-tuan"
        ),
        pytest.param(_with_first_week(days=[-1, 5, 0, 0, 0, 0, 0], total=4), id="so-am"),
        pytest.param(_with_first_week(days=[True, 6, 4, 7, 2, 0, 0], total=20), id="true-la-so"),
        pytest.param(_with_first_week(days=["7", 6, 4, 7, 2, 0, 0], total=26), id="chuoi-la-so"),
        pytest.param(_with_first_week(total=27), id="total-khac-tong"),
        pytest.param(_with_first_week(week=1792281600 + 86400), id="tuan-bat-dau-thu-hai"),
        pytest.param(_with_first_week(week=1792281600 + 3600), id="tuan-bat-dau-1-gio-sang"),
        pytest.param(_with_first_week(week="1792281600"), id="week-la-chuoi"),
        pytest.param(_with_first_week(week=1792281600.5), id="week-la-so-thuc"),
        pytest.param(_with_first_week(week=-1), id="week-am"),
        pytest.param(_with_first_week(week=10**20), id="week-vuot-pham-vi"),
        pytest.param([{"week": 1792281600, "total": 26}], id="thieu-days"),
        pytest.param(["không phải object"], id="phan-tu-khong-phai-object"),
        pytest.param({"message": "không phải mảng"}, id="khong-phai-mang"),
    ],
)
def test_star_history_rejects_malformed_weeks(
    client: GitHubClient, http_mock: respx.MockRouter, body: object
) -> None:
    http_mock.get(HISTORY_URL).respond(json=body)

    with pytest.raises(GitHubResponseError):
        client.star_history(42976210)


def test_star_history_not_found_raises_named_error(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    http_mock.get(HISTORY_URL).respond(404, json={"message": "Not Found"})

    with pytest.raises(GitHubNotFoundError, match="Not Found"):
        client.star_history(42976210)


def test_star_history_counts_against_budget(
    http_mock: respx.MockRouter, fake_time: FakeTime
) -> None:
    route = http_mock.get(HISTORY_URL).respond(json=load_fixture_list("star_history_old.json"))

    with make_client(fake_time, budget=CallBudget(1)) as github:
        github.star_history(42976210)
        with pytest.raises(CallBudgetExhaustedError):
            github.star_history(42976210)

    assert route.call_count == 1


def test_star_history_accepts_what_the_fake_serves(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    today = date(2026, 10, 22)
    fake = FakeStarHistory({42976210: make_star_history({today: 9}, today=today)})
    http_mock.get(HISTORY_URL).mock(side_effect=fake)

    history = client.star_history(42976210)

    assert len(history.weeks) == 6
    assert sum(sum(week.days) for week in history.weeks) == 9
    assert fake.requested == [42976210]


@pytest.mark.parametrize("weeks", [0, 31])
def test_star_history_rejects_weeks_out_of_range(client: GitHubClient, weeks: int) -> None:
    with pytest.raises(ValueError, match="weeks"):
        client.star_history(42976210, weeks=weeks)


# --- Nợ D-008: ngân sách không bị trừ khi chưa gọi; giờ chờ theo đồng hồ GitHub ------------------


class _StopPressedError(Exception):
    """Giả lập người dùng bấm Dừng đúng lúc client đang chờ giãn nhịp."""


def _pacing_client(fake_time: FakeTime, *, sleep: Any, budget: CallBudget) -> GitHubClient:
    pacer = RequestPacer(
        min_interval=2.1,
        sleep=sleep,
        clock=fake_time.monotonic,
        wall_clock=fake_time.time,
        jitter=lambda: 0.0,
    )
    return GitHubClient(
        token="test-token", api_url=API_URL, timeout_seconds=5.0, pacer=pacer, budget=budget
    )


def test_stop_while_waiting_to_call_does_not_spend_budget(
    http_mock: respx.MockRouter, fake_time: FakeTime
) -> None:
    def stop_on_wait(seconds: float) -> None:
        raise _StopPressedError

    budget = CallBudget(5)
    http_mock.get(SEARCH_URL).respond(json=load_fixture("search_repositories.json"))
    with _pacing_client(fake_time, sleep=stop_on_wait, budget=budget) as github:
        github.search_repositories("topic:ai-agent")  # lượt đầu không phải chờ
        with pytest.raises(_StopPressedError):
            github.search_repositories("topic:ai-agent")  # phải chờ 2,1 giây → bị Dừng

    assert budget.used == 1  # lượt bị Dừng chưa gọi thì không bị tính


def test_exhausted_budget_refuses_without_waiting(
    http_mock: respx.MockRouter, fake_time: FakeTime
) -> None:
    budget = CallBudget(1)
    http_mock.get(SEARCH_URL).respond(json=load_fixture("search_repositories.json"))
    with _pacing_client(fake_time, sleep=fake_time.sleep, budget=budget) as github:
        github.search_repositories("topic:ai-agent")
        with pytest.raises(CallBudgetExhaustedError):
            github.search_repositories("topic:ai-agent")

    assert fake_time.sleeps == []  # hết ngân sách thì từ chối ngay, không chờ giãn nhịp vô ích


def test_rate_limit_wait_follows_github_date_header_not_local_clock(
    client: GitHubClient, http_mock: respx.MockRouter, fake_time: FakeTime
) -> None:
    github_now = int(fake_time.time()) - 600  # đồng hồ máy nhanh hơn GitHub 10 phút
    limited = httpx.Response(
        403,
        headers={
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": str(github_now + 30),
            "date": format_datetime(datetime.fromtimestamp(github_now, tz=UTC), usegmt=True),
        },
        json={"message": "API rate limit exceeded"},
    )
    ok = httpx.Response(200, json=load_fixture("search_repositories.json"))
    http_mock.get(SEARCH_URL).mock(side_effect=[limited, ok])

    client.search_repositories("topic:ai-agent")

    assert fake_time.sleeps == [pytest.approx(31, abs=1)]


def test_unreadable_date_header_is_ignored(
    client: GitHubClient, http_mock: respx.MockRouter, fake_time: FakeTime
) -> None:
    reset_epoch = int(fake_time.time()) + 30
    limited = httpx.Response(
        403,
        headers={
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": str(reset_epoch),
            "date": "not-a-date",
        },
        json={"message": "API rate limit exceeded"},
    )
    ok = httpx.Response(200, json=load_fixture("search_repositories.json"))
    http_mock.get(SEARCH_URL).mock(side_effect=[limited, ok])

    client.search_repositories("topic:ai-agent")

    assert fake_time.sleeps == [pytest.approx(31, abs=1)]


# --- Số issue/PR đang mở (F-006) --------------------------------------------------------------


def test_search_reads_open_issue_count(client: GitHubClient, http_mock: respx.MockRouter) -> None:
    http_mock.get(SEARCH_URL).respond(json=load_fixture("search_repositories.json"))

    page = client.search_repositories("topic:ai-agent")

    assert [repo.open_issues for repo in page.items] == [50372, 234, 69]


def test_search_without_open_issue_count_leaves_it_unknown(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    payload = load_fixture("search_repositories.json")
    del payload["items"][0]["open_issues_count"]
    payload["items"][1]["open_issues_count"] = None
    http_mock.get(SEARCH_URL).respond(json=payload)

    page = client.search_repositories("topic:ai-agent")

    assert [repo.open_issues for repo in page.items] == [None, None, 69]


@pytest.mark.parametrize("bad_value", ["12", True, -1])
def test_search_rejects_wrong_open_issue_count(
    client: GitHubClient, http_mock: respx.MockRouter, bad_value: object
) -> None:
    payload = load_fixture("search_repositories.json")
    payload["items"][0]["open_issues_count"] = bad_value
    http_mock.get(SEARCH_URL).respond(json=payload)

    with pytest.raises(GitHubResponseError):
        client.search_repositories("topic:ai-agent")


# --- Hồ sơ chủ repo (F-006) -------------------------------------------------------------------

USER_URL = f"{API_URL}/users/octocat"


def test_get_user_parses_real_response(client: GitHubClient, http_mock: respx.MockRouter) -> None:
    http_mock.get(USER_URL).respond(json=load_fixture("user.json"))

    user = client.get_user("octocat")

    assert user.login == "octocat"
    assert user.github_id == 583231
    assert user.account_type == "User"
    assert user.created_at == datetime(2011, 1, 25, 18, 44, 36, tzinfo=UTC)
    assert user.followers == 24725
    assert user.public_repos == 8


def test_get_user_keeps_login_case_in_path(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    route = http_mock.get(f"{API_URL}/users/Octo-Cat9").respond(json=load_fixture("user.json"))

    client.get_user("Octo-Cat9")

    assert route.call_count == 1


def test_get_user_not_found_raises_named_error(
    client: GitHubClient, http_mock: respx.MockRouter
) -> None:
    http_mock.get(USER_URL).respond(404, json={"message": "Not Found"})

    with pytest.raises(GitHubNotFoundError):
        client.get_user("octocat")


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [("id", "583231"), ("followers", None), ("public_repos", True), ("created_at", "2011-01-25")],
)
def test_get_user_rejects_wrong_field_type(
    client: GitHubClient, http_mock: respx.MockRouter, field: str, bad_value: object
) -> None:
    payload = load_fixture("user.json")
    payload[field] = bad_value
    http_mock.get(USER_URL).respond(json=payload)

    with pytest.raises(GitHubResponseError):
        client.get_user("octocat")


@pytest.mark.parametrize("login", ["", "../repos", "a b", "a/b", "x" * 40, "octo?cat"])
def test_get_user_rejects_odd_login_without_calling(client: GitHubClient, login: str) -> None:
    # Không có route nào được khai báo: lỡ gọi mạng thì respx báo lỗi khác ValueError.
    with pytest.raises(ValueError, match="login"):
        client.get_user(login)


def test_get_user_counts_against_budget(http_mock: respx.MockRouter, fake_time: FakeTime) -> None:
    route = http_mock.get(USER_URL).respond(json=load_fixture("user.json"))

    with make_client(fake_time, budget=CallBudget(1)) as github:
        github.get_user("octocat")
        with pytest.raises(CallBudgetExhaustedError):
            github.get_user("octocat")

    assert route.call_count == 1
