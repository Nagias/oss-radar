"""Công cụ giả lập cho test: GitHub tìm kiếm hiểu truy vấn, và đồng hồ giả (không ngủ thật).

Mỗi repo giả là bản sao của một repo THẬT đã lưu (tests/fixtures/github/), chỉ thay id, tên, star,
ngày tạo — hình dạng dữ liệu luôn đúng như GitHub trả.
"""

import copy
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from typing import Any

import httpx

from tests.factories import load_fixture

MAX_RESULTS = 1000  # GitHub chỉ trả tối đa 1.000 kết quả cho một truy vấn.
_STARS_MIN = re.compile(r"(?<![\w-])stars:>=(\d+)")
_STARS_RANGE = re.compile(r"(?<![\w-])stars:(\d+)\.\.(\d+)")
_CREATED = re.compile(r"(?<![\w-])created:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})")
_HISTORY_PATH = re.compile(r"/repositories/(\d+)/stargazers/history$")


class FakeTime:
    """Đồng hồ giả: `sleep` không chờ thật mà cộng thẳng vào giờ, và ghi lại từng lần ngủ."""

    def __init__(self) -> None:
        self._monotonic = 1000.0
        self._wall = time.time()
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._monotonic

    def time(self) -> float:
        return self._wall

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._monotonic += seconds
        self._wall += seconds


def make_search_items(
    count: int,
    *,
    start: date,
    end: date,
    stars: Callable[[int], int],
    id_start: int = 1,
) -> list[dict[str, Any]]:
    """Dựng `count` repo, ngày tạo rải đều từ `start` tới `end`; repo thứ i có `stars(i)` star."""
    template = load_fixture("github/search_repositories.json")["items"][0]
    span_days = (end - start).days + 1
    items: list[dict[str, Any]] = []
    for index in range(count):
        repo_id = id_start + index
        created_day = start + timedelta(days=(index * span_days) // count)
        item = copy.deepcopy(template)
        item.update(
            id=repo_id,
            name=f"repo-{repo_id}",
            full_name=f"gia-lap/repo-{repo_id}",
            html_url=f"https://github.com/gia-lap/repo-{repo_id}",
            stargazers_count=stars(index),
            created_at=datetime.combine(created_day, clock_time(12, 0), tzinfo=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        )
        items.append(item)
    return items


class FakeGitHubSearch:
    """Dùng làm `side_effect` của respx cho GET /search/repositories."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.queries: list[str] = []
        self.fail_when: Callable[[str], int | None] | None = None
        self.incomplete_when: Callable[[str], bool] | None = None
        # Gọi mỗi khi nhận truy vấn — để test giả lập việc xảy ra giữa chừng một lần quét.
        self.on_query: Callable[[str], None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        query = params.get("q", "")
        page = int(params.get("page", "1"))
        per_page = int(params.get("per_page", "30"))
        self.queries.append(query)
        if self.on_query is not None:
            self.on_query(query)

        if self.fail_when is not None and (status := self.fail_when(query)) is not None:
            return httpx.Response(status, json={"message": "lỗi giả lập"})
        if (page - 1) * per_page >= MAX_RESULTS:
            return httpx.Response(
                422, json={"message": "Only the first 1000 search results are available"}
            )

        matched = sorted(
            (item for item in self.items if _matches(item, query)),
            key=lambda item: (-item["stargazers_count"], item["id"]),
        )
        first = (page - 1) * per_page
        body = {
            "total_count": len(matched),
            "incomplete_results": bool(self.incomplete_when and self.incomplete_when(query)),
            "items": matched[first : first + per_page],
        }
        headers = {"x-ratelimit-remaining": "29", "x-ratelimit-reset": str(int(time.time()) + 60)}
        return httpx.Response(200, json=body, headers=headers)


def make_star_history(
    daily: dict[date, int], *, today: date, weeks: int = 6
) -> list[dict[str, Any]]:
    """Dựng lịch sử star theo tuần (mới nhất trước) đúng hình dạng GitHub trả.

    Mỗi tuần bắt đầu Chủ nhật 00:00 UTC; tuần mới nhất là tuần chứa `today`. `daily` là star mới
    theo ngày UTC, ngày không có thì là 0. Ngày nằm ngoài `weeks` tuần dựng ra bị bỏ, giống việc
    GitHub chỉ trả `per_page` tuần.
    """
    newest_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    history: list[dict[str, Any]] = []
    for weeks_back in range(weeks):
        sunday = newest_sunday - timedelta(weeks=weeks_back)
        days = [daily.get(sunday + timedelta(days=offset), 0) for offset in range(7)]
        history.append(
            {
                "week": int(datetime.combine(sunday, clock_time(0, 0), tzinfo=UTC).timestamp()),
                "total": sum(days),
                "days": days,
            }
        )
    return history


class FakeStarHistory:
    """Dùng làm `side_effect` của respx cho GET /repositories/{id}/stargazers/history."""

    def __init__(self, histories: dict[int, list[dict[str, Any]]]) -> None:
        self.histories = histories
        self.requested: list[int] = []
        self.fail_when: Callable[[int], int | None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        found = _HISTORY_PATH.search(request.url.path)
        if found is None:
            raise ValueError(f"không phải đường dẫn lịch sử star: {request.url.path}")
        repo_id = int(found.group(1))
        self.requested.append(repo_id)

        if self.fail_when is not None and (status := self.fail_when(repo_id)) is not None:
            return httpx.Response(status, json={"message": "lỗi giả lập"})
        if repo_id not in self.histories:
            return httpx.Response(404, json={"message": "Not Found"})
        headers = {"x-ratelimit-remaining": "59", "x-ratelimit-reset": str(int(time.time()) + 3600)}
        return httpx.Response(200, json=self.histories[repo_id], headers=headers)


def _matches(item: dict[str, Any], query: str) -> bool:
    stars = int(item["stargazers_count"])
    if (found := _STARS_MIN.search(query)) and stars < int(found.group(1)):
        return False
    if (found := _STARS_RANGE.search(query)) and not (
        int(found.group(1)) <= stars <= int(found.group(2))
    ):
        return False
    created = str(item["created_at"])[:10]
    found = _CREATED.search(query)
    return found is None or found.group(1) <= created <= found.group(2)


_USER_PATH = re.compile(r"/users/([A-Za-z0-9-]+)$")


def make_user(
    login: str, *, created: date, followers: int = 10, public_repos: int = 30
) -> dict[str, Any]:
    """Hồ sơ tài khoản giả: bản sao của phản hồi THẬT `GET /users/octocat`, thay vài trường."""
    user = copy.deepcopy(load_fixture("github/user.json"))
    user.update(
        login=login,
        followers=followers,
        public_repos=public_repos,
        created_at=datetime.combine(created, clock_time(9, 0), tzinfo=UTC)
        .isoformat()
        .replace("+00:00", "Z"),
    )
    return user


class FakeGitHubUsers:
    """Dùng làm `side_effect` của respx cho GET /users/{login}; login không có thì trả 404."""

    def __init__(self, users: dict[str, dict[str, Any]]) -> None:
        self.users = {login.lower(): user for login, user in users.items()}
        self.requested: list[str] = []
        self.fail_when: Callable[[str], int | None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        found = _USER_PATH.search(request.url.path)
        if found is None:
            raise ValueError(f"không phải đường dẫn hồ sơ tài khoản: {request.url.path}")
        login = found.group(1)
        self.requested.append(login)

        if self.fail_when is not None and (status := self.fail_when(login)) is not None:
            return httpx.Response(status, json={"message": "lỗi giả lập"})
        user = self.users.get(login.lower())
        if user is None:
            return httpx.Response(404, json={"message": "Not Found"})
        headers = {"x-ratelimit-remaining": "59", "x-ratelimit-reset": str(int(time.time()) + 3600)}
        return httpx.Response(200, json=user, headers=headers)


# --- 9router giả (F-010) ----------------------------------------------------------------------

_PROMPT_ID = re.compile(r"^id=(\d+) \|", re.MULTILINE)
LLM_CHAT_URL = "http://localhost:20128/v1/chat/completions"
DEFAULT_LABELS: tuple[list[str], list[str]] = (["developer"], ["devtools"])


class FakeLlm:
    """Dùng làm `side_effect` của respx cho POST /chat/completions của 9router.

    Đọc id repo trong prompt, trả nhãn đúng hình dạng phản hồi THẬT (tests/fixtures/llm/), kể cả
    khung ```json mà Gemini hay bọc. `labels` quyết định nhãn theo id; `fail_with(lần gọi thứ n)`
    trả mã lỗi HTTP; `garbled` là các lần gọi trả nội dung không phải JSON.
    """

    def __init__(self, labels: Callable[[int], tuple[list[str], list[str]]] | None = None) -> None:
        self.labels = labels or (lambda _id: DEFAULT_LABELS)
        self.calls: list[list[int]] = []
        self.fail_with: Callable[[int], int | None] | None = None
        self.garbled: set[int] = set()
        self.skip_ids: set[int] = set()
        # Gọi mỗi khi nhận một lượt — để test giả lập việc xảy ra giữa chừng.
        self.on_call: Callable[[int], None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user = next(m["content"] for m in body["messages"] if m["role"] == "user")
        ids = [int(found) for found in _PROMPT_ID.findall(user)]
        self.calls.append(ids)
        call_number = len(self.calls)
        if self.on_call is not None:
            self.on_call(call_number)
        if self.fail_with is not None and (status := self.fail_with(call_number)) is not None:
            return httpx.Response(status, json={"error": {"message": "lỗi giả lập"}})
        if call_number in self.garbled:
            content = "Xin lỗi, tôi không chắc."
        else:
            repos = [
                {
                    "id": repo_id,
                    "audience": self.labels(repo_id)[0],
                    "aspects": self.labels(repo_id)[1],
                    "reason": f"từ khoá của repo {repo_id}",
                }
                for repo_id in ids
                if repo_id not in self.skip_ids
            ]
            content = "```json\n" + json.dumps({"repos": repos}, ensure_ascii=False) + "\n```"
        reply = copy.deepcopy(load_fixture("llm/chat_completion_classify.json"))
        reply["choices"][0]["message"]["content"] = content
        return httpx.Response(200, json=reply)
