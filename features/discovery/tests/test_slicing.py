"""Chia lát truy vấn: vượt trần 1.000 kết quả của GitHub bằng cách chia theo ngày tạo và star."""

from datetime import date

import pytest

from features.discovery.slicing import (
    EARLIEST_DATE,
    SliceRange,
    build_query,
    find_forbidden_qualifier,
    pages_needed,
    resolve_root_range,
    split,
)

JANUARY = SliceRange(date(2026, 1, 1), date(2026, 1, 31), 10, None)
ONE_DAY = date(2026, 1, 5)


def test_query_with_min_stars_only() -> None:
    assert build_query("topic:ai-agent", JANUARY) == (
        "topic:ai-agent stars:>=10 created:2026-01-01..2026-01-31"
    )


def test_query_with_star_range() -> None:
    rng = SliceRange(date(2026, 1, 1), date(2026, 1, 31), 10, 999)

    assert build_query("  topic:ai-agent ", rng) == (
        "topic:ai-agent stars:10..999 created:2026-01-01..2026-01-31"
    )


def test_split_dates_newer_half_first() -> None:
    first, later = split(JANUARY, top_stars=500) or pytest.fail("phải chia được")

    assert first == SliceRange(date(2026, 1, 17), date(2026, 1, 31), 10, None)
    assert later == SliceRange(date(2026, 1, 1), date(2026, 1, 16), 10, None)


def test_split_two_days_into_single_days() -> None:
    rng = SliceRange(date(2026, 1, 1), date(2026, 1, 2), 10, None)

    first, later = split(rng, top_stars=500) or pytest.fail("phải chia được")

    assert (first.created_from, first.created_to) == (date(2026, 1, 2), date(2026, 1, 2))
    assert (later.created_from, later.created_to) == (date(2026, 1, 1), date(2026, 1, 1))


def test_split_single_day_by_stars_higher_first() -> None:
    rng = SliceRange(ONE_DAY, ONE_DAY, 10, None)

    first, later = split(rng, top_stars=500) or pytest.fail("phải chia được")

    assert first == SliceRange(ONE_DAY, ONE_DAY, 256, 500)
    assert later == SliceRange(ONE_DAY, ONE_DAY, 10, 255)


def test_split_single_day_uses_stars_max_when_given() -> None:
    rng = SliceRange(ONE_DAY, ONE_DAY, 10, 100)

    first, later = split(rng, top_stars=5000) or pytest.fail("phải chia được")

    assert first == SliceRange(ONE_DAY, ONE_DAY, 56, 100)
    assert later == SliceRange(ONE_DAY, ONE_DAY, 10, 55)


@pytest.mark.parametrize(
    ("rng", "top_stars"),
    [(SliceRange(ONE_DAY, ONE_DAY, 7, 7), 7), (SliceRange(ONE_DAY, ONE_DAY, 7, None), 7)],
)
def test_cannot_split_single_day_single_star(rng: SliceRange, top_stars: int) -> None:
    assert split(rng, top_stars=top_stars) is None


@pytest.mark.parametrize(
    ("total", "pages"),
    [(0, 0), (1, 1), (100, 1), (101, 2), (250, 3), (1000, 10), (5000, 10)],
)
def test_pages_needed(total: int, pages: int) -> None:
    assert pages_needed(total) == pages


@pytest.mark.parametrize(
    ("query", "found"),
    [
        ("topic:x Stars:>5", "stars:"),
        ("created:>2024-01-01 topic:x", "created:"),
        ("topic:x SORT:updated", "sort:"),
        ("topic:x -stars:>5", "stars:"),
        ("-Created:2020-01-01..2020-02-01 topic:x", "created:"),
        ("topic:github-stars", None),
        ("language:python ai agent", None),
    ],
)
def test_forbidden_qualifiers_any_case(query: str, found: str | None) -> None:
    assert find_forbidden_qualifier(query) == found


def test_root_range_defaults_to_whole_history() -> None:
    rng = resolve_root_range(
        created_from=None, created_to=None, min_stars=10, max_stars=None, today=date(2026, 10, 22)
    )

    assert rng == SliceRange(EARLIEST_DATE, date(2026, 10, 22), 10, None)
    assert date(2008, 1, 1) == EARLIEST_DATE


def test_root_range_keeps_given_bounds() -> None:
    rng = resolve_root_range(
        created_from=date(2025, 1, 1),
        created_to=date(2025, 6, 30),
        min_stars=0,
        max_stars=999,
        today=date(2026, 10, 22),
    )

    assert rng == SliceRange(date(2025, 1, 1), date(2025, 6, 30), 0, 999)
