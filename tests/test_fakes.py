"""Công cụ giả lập phải giống GitHub thật ở chỗ test dựa vào: lọc, đếm, phân trang, trần 1.000."""

from datetime import UTC, date, datetime

import httpx

from tests.factories import load_fixture_list
from tests.fakes import (
    FakeGitHubSearch,
    FakeStarHistory,
    FakeTime,
    make_search_items,
    make_star_history,
)

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


def _sunday_epoch(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp())


def test_make_star_history_places_counts_on_utc_days() -> None:
    today = date(2026, 10, 22)  # thứ Năm
    daily = {
        today: 5,  # thứ Năm của tuần mới nhất
        date(2026, 10, 18): 7,  # Chủ nhật, đầu tuần mới nhất
        date(2026, 10, 17): 3,  # thứ Bảy, cuối tuần trước
        date(2026, 10, 4): 2,  # Chủ nhật của tuần thứ ba tính ngược
        date(2026, 9, 1): 9,  # ngoài ba tuần dựng ra: GitHub không trả nên bị bỏ
    }

    weeks = make_star_history(daily, today=today, weeks=3)

    assert [week["week"] for week in weeks] == [
        _sunday_epoch(2026, 10, 18),
        _sunday_epoch(2026, 10, 11),
        _sunday_epoch(2026, 10, 4),
    ]
    assert [week["days"] for week in weeks] == [
        [7, 0, 0, 0, 5, 0, 0],
        [0, 0, 0, 0, 0, 0, 3],
        [2, 0, 0, 0, 0, 0, 0],
    ]
    assert [week["total"] for week in weeks] == [12, 3, 2]


def test_make_star_history_has_the_shape_of_the_real_response() -> None:
    real_week = load_fixture_list("github/star_history_old.json")[0]

    weeks = make_star_history({}, today=date(2026, 10, 22))

    assert len(weeks) == 6
    assert {key: type(value) for key, value in weeks[0].items()} == {
        key: type(value) for key, value in real_week.items()
    }
    assert weeks[0]["days"] == [0] * 7
    assert weeks[0]["total"] == 0


def _history_request(repo_id: int) -> httpx.Request:
    url = f"https://api.github.com/repositories/{repo_id}/stargazers/history"
    return httpx.Request("GET", url, params={"per_page": 6})


def test_fake_star_history_serves_known_id() -> None:
    weeks = make_star_history({date(2026, 10, 22): 4}, today=date(2026, 10, 22))
    fake = FakeStarHistory({42976210: weeks})

    response = fake(_history_request(42976210))

    assert response.status_code == 200
    assert response.json() == weeks
    assert fake.requested == [42976210]


def test_fake_star_history_404_for_unknown_id() -> None:
    fake = FakeStarHistory({42976210: make_star_history({}, today=date(2026, 10, 22))})

    response = fake(_history_request(999))

    assert response.status_code == 404
    assert response.json() == {"message": "Not Found"}
    assert fake.requested == [999]


def test_fake_star_history_can_fail_for_chosen_ids() -> None:
    weeks = make_star_history({}, today=date(2026, 10, 22))
    fake = FakeStarHistory({1: weeks, 2: weeks})
    fake.fail_when = lambda repo_id: 502 if repo_id == 2 else None

    assert fake(_history_request(1)).status_code == 200
    assert fake(_history_request(2)).status_code == 502
