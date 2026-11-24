"""Chuỗi bộ lọc chuẩn của góc nhìn: ổn định, bỏ mặc định, đọc lại ra đúng bộ lọc."""

from dataclasses import replace

import pytest

from features.browse import services
from features.browse.filters import BrowseFilters, canonical_query

FULL = BrowseFilters(
    tab="all",
    q="video agent",
    audience=("marketer", "creator", "creator"),
    aspects=("video",),
    language="Python",
    min_stars=100,
    max_stars=5_000,
    created_days=90,
    commercial=True,
    unclassified=True,
    show_suspicious=True,
    sort="forks",
    scan=7,
    page=4,
    view=3,
)


def test_canonical_query_has_a_fixed_order_and_drops_page_scan_view() -> None:
    assert canonical_query(FULL) == (
        "tab=all&q=video+agent&audience=creator&audience=marketer&aspects=video&language=python"
        "&min_stars=100&max_stars=5000&created_days=90&commercial=on&unclassified=on"
        "&show_suspicious=on&sort=forks"
    )


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (BrowseFilters(), ""),
        (BrowseFilters(sort="gain"), ""),  # mặc định của tab Trending
        (BrowseFilters(tab="rising", sort="potential"), "tab=rising"),
        (BrowseFilters(tab="rising", sort="forks"), "tab=rising"),  # cách sắp của tab khác
        (BrowseFilters(tab="all", sort="stars"), "tab=all"),
    ],
)
def test_canonical_query_drops_defaults(filters: BrowseFilters, expected: str) -> None:
    assert canonical_query(filters) == expected


def test_saved_query_reads_back_into_the_same_filters() -> None:
    back = services.filters_from_query(canonical_query(FULL))

    assert back == replace(
        FULL, audience=("creator", "marketer"), language="python", scan=None, page=1, view=None
    )


def test_order_of_the_address_does_not_matter() -> None:
    one = services.filters_from_query("aspects=video&tab=rising&audience=marketer&audience=creator")
    two = services.filters_from_query("audience=creator&tab=rising&aspects=video&audience=marketer")

    assert canonical_query(one) == canonical_query(two)
    assert one.audience == ("marketer", "creator")  # đọc được thật, không bị bỏ vì mã lạ


def test_equivalent_filters_share_one_saved_query() -> None:
    messy = BrowseFilters(q="  video   agent a b c d e  ", language="PYTHON", min_stars=0)
    clean = BrowseFilters(q="video agent a b c", language="python")

    assert canonical_query(messy) == canonical_query(clean) == "q=video+agent+a+b+c&language=python"
