"""Công cụ giả lập cho test: GitHub tìm kiếm hiểu truy vấn, và đồng hồ giả (không ngủ thật).

Mỗi repo giả là bản sao của một repo THẬT đã lưu (tests/fixtures/github/), chỉ thay id, tên, star,
ngày tạo — hình dạng dữ liệu luôn đúng như GitHub trả.
"""

import copy
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

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        query = params.get("q", "")
        page = int(params.get("page", "1"))
        per_page = int(params.get("per_page", "30"))
        self.queries.append(query)

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
