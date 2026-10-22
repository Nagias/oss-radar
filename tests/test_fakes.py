"""Công cụ giả lập phải giống GitHub thật ở chỗ test dựa vào: lọc, đếm, phân trang, trần 1.000."""

from datetime import date

import httpx

from tests.fakes import FakeGitHubSearch, FakeTime, make_search_items

SEARCH_URL = "https://api.github.com/search/repositories"


def _search(fake: FakeGitHubSearch, q: str, *, page: int = 1) -> httpx.Response:
    request = httpx.Request("GET", SEARCH_URL, params={"q": q, "per_page": 100, "page": page})
    return fake(request)


def test_fake_search_filters_by_stars_and_created() -> None:
    items = make_search_items(300, start=date(2026, 1, 1), end=date(2026, 1, 30), stars=lambda i: i)
    fake = FakeGitHubSearch(items)

    body = _search(fake, "topic:x stars:>=100 created:2026-01-01..2026-01-30").json()

    assert body["total_count"] == 200
    assert len(body["items"]) == 100
    assert body["items"][0]["stargazers_count"] == 299
    early = [it for it in items if it["created_at"][:10] <= "2026-01-10"]
    narrowed = _search(fake, "topic:x stars:>=0 created:2026-01-01..2026-01-10").json()
    assert narrowed["total_count"] == len(early)
    assert fake.queries[-1] == "topic:x stars:>=0 created:2026-01-01..2026-01-10"


def test_fake_search_understands_star_ranges() -> None:
    items = make_search_items(50, start=date(2026, 1, 1), end=date(2026, 1, 1), stars=lambda i: i)

    body = _search(FakeGitHubSearch(items), "topic:x stars:10..19 created:2026-01-01..2026-01-01")

    assert body.json()["total_count"] == 10


def test_fake_search_refuses_beyond_first_1000_results() -> None:
    items = make_search_items(1500, start=date(2026, 1, 1), end=date(2026, 3, 1), stars=lambda i: i)
    fake = FakeGitHubSearch(items)
    q = "topic:x stars:>=0 created:2026-01-01..2026-03-01"

    assert len(_search(fake, q, page=10).json()["items"]) == 100
    assert _search(fake, q, page=11).status_code == 422


def test_fake_search_can_fail_and_flag_incomplete() -> None:
    items = make_search_items(5, start=date(2026, 1, 1), end=date(2026, 1, 1), stars=lambda i: i)
    fake = FakeGitHubSearch(items)
    fake.fail_when = lambda q: 502 if "2026-01-01" in q else None
    q = "topic:x stars:>=0 created:2026-01-01..2026-01-01"

    assert _search(fake, q).status_code == 502

    fake.fail_when = None
    fake.incomplete_when = lambda q: True
    assert _search(fake, q).json()["incomplete_results"] is True


def test_fake_time_sleep_advances_both_clocks() -> None:
    clock = FakeTime()
    start_mono, start_wall = clock.monotonic(), clock.time()

    clock.sleep(2.5)

    assert clock.monotonic() == start_mono + 2.5
    assert clock.time() == start_wall + 2.5
    assert clock.sleeps == [2.5]
