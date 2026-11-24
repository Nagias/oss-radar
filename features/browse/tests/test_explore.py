"""Trang Khám phá (F-012): ba tab Trending / Đang lên / Toàn kho, chung ô tìm và thanh lọc."""

import html
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import Client
from django.utils import timezone

from features.browse import services
from features.browse.services import BrowseFilters
from features.browse.tests.conftest import add_repo, label
from features.catalog.models import Repository
from features.rising.models import DailyRun, RisingCheck
from tests.html import nav_links

pytestmark = pytest.mark.django_db

TRENDING = BrowseFilters(tab="trending")
RISING = BrowseFilters(tab="rising")
ALL = BrowseFilters(tab="all")
WINDOW_END = date(2026, 11, 23)


def report(day: date | None = None, **fields: Any) -> DailyRun:
    fields.setdefault("trending_budget", 300)  # lượt có token: có xác minh trending
    return DailyRun.objects.create(
        day=day or timezone.localdate(),
        status=DailyRun.Status.SUCCEEDED,
        step=DailyRun.Step.REPORT,
        window_end=WINDOW_END,
        **fields,
    )


def check(
    run: DailyRun,
    repo: Repository,
    *,
    gain: int,
    trending: bool = False,
    rising: bool = False,
    verified: bool = True,
) -> RisingCheck:
    pool = RisingCheck.Pool.RISING if repo.stars < 1000 else RisingCheck.Pool.TRENDING
    return RisingCheck.objects.create(
        daily_run=run,
        repository=repo,
        stars=repo.stars,
        pool=pool,
        source=RisingCheck.Source.HISTORY if verified else RisingCheck.Source.SNAPSHOT,
        gain_1d=gain // 7 if verified else None,
        gain_7d=gain,
        gain_30d=gain * 3 if verified else None,
        series=[gain // 7] * 30 if verified else [],
        window_end=WINDOW_END if verified else None,
        is_trending=trending,
        is_rising=rising,
    )


def ids(filters: BrowseFilters) -> list[int]:
    page = services.explore(filters)
    rows = page.report_rows if filters.tab != "all" else page.all_rows
    return [row.repository.github_id for row in rows]


def mixed() -> DailyRun:
    """Báo cáo mới nhất: 2 trending (1 lớn, 1 nhỏ), 2 rising (1 trùng), 1 repo chỉ có trong kho."""
    run = report()
    check(run, add_repo(1, stars=50_000), gain=2_000, trending=True)
    check(run, add_repo(2, stars=800), gain=300, trending=True, rising=True)
    check(run, add_repo(3, stars=400), gain=90, rising=True)
    check(run, add_repo(4, stars=9_000), gain=150)  # đã xét, không đạt
    add_repo(5, stars=70_000)  # có trong kho, không có trong báo cáo
    return run


# --- Tập repo của từng tab ----------------------------------------------------------------------


def test_each_tab_lists_its_own_set() -> None:
    mixed()

    assert ids(TRENDING) == [1, 2]
    assert ids(RISING) == [2, 3]  # điểm Tiềm năng: repo nhỏ tăng mạnh trước
    assert ids(ALL) == [5, 1, 4, 2, 3]  # Toàn kho: nhiều star trước


def test_report_tabs_only_read_the_latest_finished_report() -> None:
    old = report(timezone.localdate() - timedelta(days=1))
    check(old, add_repo(9, stars=30_000), gain=5_000, trending=True)
    mixed()
    DailyRun.objects.create(
        day=timezone.localdate() + timedelta(days=1),
        status=DailyRun.Status.RUNNING,
        step=DailyRun.Step.VERIFY,
    )

    page = services.explore(TRENDING)

    assert [row.repository.github_id for row in page.report_rows] == [1, 2]
    assert page.run is not None
    assert page.run.day == timezone.localdate()


def test_common_filters_apply_on_every_tab() -> None:
    mixed()
    label(Repository.objects.get(github_id=2), audience=("creator",), aspects=("video",))
    Repository.objects.filter(github_id=1).update(language="Go")

    creators = replace(TRENDING, audience=("creator",))
    go = replace(TRENDING, language="go")
    big = replace(RISING, min_stars=500)

    assert ids(creators) == [2]
    assert ids(go) == [1]
    assert ids(big) == [2]
    assert ids(replace(ALL, audience=("creator",))) == [2]


def test_search_needs_every_word_in_name_description_or_topics() -> None:
    run = report()
    both = add_repo(1, stars=5_000, description="Tạo video bằng AI", topics=["ai-agent"])
    only_video = add_repo(2, stars=5_000, description="Dựng video nhanh", topics=[])
    check(run, both, gain=500, trending=True)
    check(run, only_video, gain=400, trending=True)

    assert ids(replace(TRENDING, q="video agent")) == [1]
    assert ids(replace(TRENDING, q="VIDEO")) == [1, 2]
    assert ids(replace(ALL, q="repo-2 dựng")) == [2]  # tên repo cũng được tìm
    # Chỉ 5 từ đầu được dùng: từ thứ 6 không khớp cũng không loại repo.
    assert ids(replace(TRENDING, q="video ai agent tạo bằng khong_co")) == [1]


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("", [1, 2, 3]),  # mặc định: tăng 7 ngày
        ("gain", [1, 2, 3]),
        ("percent", [3, 2, 1]),
        ("stars", [1, 2, 3]),
        ("lung_tung", [1, 2, 3]),
    ],
)
def test_trending_sorts(sort: str, expected: list[int]) -> None:
    run = report()
    check(run, add_repo(1, stars=80_000), gain=4_000, trending=True)  # 5,3%
    check(run, add_repo(2, stars=9_000), gain=1_000, trending=True)  # 12,5%
    check(run, add_repo(3, stars=1_500), gain=600, trending=True)  # 66,7%

    assert ids(replace(TRENDING, sort=sort)) == expected


def test_rising_sorts_default_to_potential_and_offer_created() -> None:
    run = report()
    check(
        run,
        add_repo(1, stars=990, created_at=datetime(2024, 1, 1, tzinfo=UTC)),
        gain=60,
        rising=True,
    )
    check(
        run,
        add_repo(2, stars=60, created_at=datetime(2026, 1, 1, tzinfo=UTC)),
        gain=55,
        rising=True,
    )

    assert ids(RISING) == [2, 1]
    assert ids(replace(RISING, sort="gain")) == [1, 2]
    assert ids(replace(RISING, sort="created")) == [2, 1]
    assert services.explore(RISING).sort == "potential"
    assert services.explore(replace(RISING, sort="forks")).sort == "potential"  # không có ở tab này


def test_high_suspicion_is_hidden_with_live_scores_unless_asked() -> None:
    run = report()
    created = timezone.now() - timedelta(days=30)
    fishy = add_repo(
        1,
        stars=613,
        forks=2,
        created_at=created,
        pushed_at=created.replace(hour=18),
    )
    check(run, fishy, gain=300, trending=True, rising=True)
    check(run, add_repo(2, stars=5_000, forks=900), gain=400, trending=True)

    hidden = services.explore(TRENDING)
    shown = services.explore(replace(TRENDING, show_suspicious=True))

    assert [row.repository.github_id for row in hidden.report_rows] == [2]
    assert hidden.hidden_count == 1
    assert [row.repository.github_id for row in shown.report_rows] == [2, 1]
    assert shown.hidden_count == 0


def test_report_tabs_without_any_report_are_empty() -> None:
    add_repo(1, stars=50_000)

    page = services.explore(TRENDING)

    assert (page.run, page.report_rows, page.total, page.unverified_count) == (None, [], 0, 0)


def test_unverified_candidates_are_counted_per_tab() -> None:
    run = mixed()
    check(run, add_repo(6, stars=4_000), gain=300, verified=False)
    check(run, add_repo(7, stars=300), gain=80, verified=False)
    check(run, add_repo(8, stars=200), gain=70, verified=False)

    assert services.explore(TRENDING).unverified_count == 1
    assert services.explore(RISING).unverified_count == 2


def test_report_tabs_show_25_rows_per_page_and_clamp_the_page() -> None:
    run = report()
    for github_id in range(1, 28):
        check(run, add_repo(github_id, stars=5_000), gain=200 + github_id, trending=True)

    first = services.explore(TRENDING)
    last = services.explore(replace(TRENDING, page=99))

    assert (len(first.report_rows), first.total, first.pages) == (25, 27, 2)
    assert (last.page, len(last.report_rows)) == (2, 2)
    assert last.first_index == 26


def test_trending_tab_query_count_does_not_grow_with_rows(
    django_assert_max_num_queries: Any,
) -> None:
    run = report()
    for github_id in range(1, 4):
        check(run, add_repo(github_id, stars=5_000), gain=500, trending=True)
    with django_assert_max_num_queries(30) as few:
        services.explore(TRENDING)
    for github_id in range(4, 40):
        repo = add_repo(github_id, stars=5_000)
        label(repo, audience=("creator",))
        check(run, repo, gain=500, trending=True)

    with django_assert_max_num_queries(len(few.captured_queries)):
        services.explore(TRENDING)


# --- Đường dẫn của trang: tab, chip đang bật, xoá tất cả -----------------------------------------


def query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(html.unescape(url)).query)


def test_tab_links_keep_filters_but_reset_sort_and_page() -> None:
    filters = BrowseFilters(tab="all", audience=("creator",), q="video", sort="forks", page=3)

    tabs = services.tab_links(filters)

    assert [(tab.key, tab.label, tab.current) for tab in tabs] == [
        ("trending", "Trending", False),
        ("rising", "Đang lên", False),
        ("all", "Toàn kho", True),
    ]
    assert query(tabs[0].url) == {"q": ["video"], "audience": ["creator"]}  # trending là mặc định
    assert query(tabs[1].url) == {"tab": ["rising"], "q": ["video"], "audience": ["creator"]}


def test_active_chips_each_remove_only_themselves() -> None:
    filters = BrowseFilters(
        tab="rising", q="video", audience=("creator", "marketer"), min_stars=100, commercial=True
    )

    chips = services.active_chips(filters)

    by_label = {chip.label: query(chip.remove_url) for chip in chips}
    assert by_label == {
        "Từ khoá: video": {
            "tab": ["rising"],
            "audience": ["creator", "marketer"],
            "min_stars": ["100"],
            "commercial": ["on"],
        },
        "Dành cho ai: Nhà sáng tạo nội dung (video, YouTube, ảnh)": {
            "tab": ["rising"],
            "q": ["video"],
            "audience": ["marketer"],
            "min_stars": ["100"],
            "commercial": ["on"],
        },
        "Dành cho ai: Marketer": {
            "tab": ["rising"],
            "q": ["video"],
            "audience": ["creator"],
            "min_stars": ["100"],
            "commercial": ["on"],
        },
        "Từ 100 star": {
            "tab": ["rising"],
            "q": ["video"],
            "audience": ["creator", "marketer"],
            "commercial": ["on"],
        },
        "Giấy phép dùng thương mại": {
            "tab": ["rising"],
            "q": ["video"],
            "audience": ["creator", "marketer"],
            "min_stars": ["100"],
        },
    }
    assert query(services.clear_url(filters)) == {"tab": ["rising"]}


# --- Trang web -----------------------------------------------------------------------------------


def test_home_page_opens_the_trending_tab(client: Client) -> None:
    mixed()

    page = client.get("/").text

    assert [link.text for link in nav_links(page, label="Loại danh sách") if link.current] == [
        "Trending"
    ]
    assert page.index('data-repo="chu/repo-1"') < page.index('data-repo="chu/repo-2"')
    assert 'data-repo="chu/repo-3"' not in page
    assert "+2.000" in page
    assert "ngưỡng 200 star và 2%" in page  # dòng "Vì sao có mặt"
    assert "<polyline" in page


def test_page_header_names_the_report_day_and_data_window(client: Client) -> None:
    mixed()

    page = client.get("/?tab=rising").text

    assert f"Báo cáo ngày {timezone.localdate():%d/%m/%Y}" in page
    assert "ngày UTC 17/11–23/11" in page  # noqa: RUF001 — khoảng 7 ngày của số liệu


def test_unknown_tab_falls_back_to_trending(client: Client) -> None:
    mixed()

    page = client.get("/", {"tab": "lung_tung"}).text

    assert 'data-repo="chu/repo-1"' in page
    assert 'data-repo="chu/repo-3"' not in page


def test_empty_states(client: Client) -> None:
    assert "Chưa có báo cáo nào" in client.get("/").text

    run = report(trending_budget=0)
    check(run, add_repo(1, stars=400), gain=90, rising=True)
    no_trending = client.get("/").text
    assert "không xác minh repo trending" in no_trending

    nothing = client.get("/", {"tab": "rising", "q": "khong_co_gi"}).text
    assert "Không có repo nào khớp bộ lọc" in nothing
    assert 'href="/?tab=rising">Xoá tất cả' in nothing


def test_live_run_banner_links_to_watch(client: Client) -> None:
    yesterday = report(timezone.localdate() - timedelta(days=1))
    check(yesterday, add_repo(1, stars=50_000), gain=2_000, trending=True)
    DailyRun.objects.create(
        day=timezone.localdate(),
        status=DailyRun.Status.RUNNING,
        step=DailyRun.Step.VERIFY,
        heartbeat_at=timezone.now(),
    )

    page = client.get("/").text

    assert "Lượt quét hôm nay đang chạy" in page
    assert 'href="/rising/watch/"' in page
    assert 'data-repo="chu/repo-1"' in page  # vẫn hiện báo cáo trước
    assert 'http-equiv="refresh"' not in page  # trang Khám phá không tự tải lại


def test_unverified_candidates_are_told_and_rising_ones_link_to_the_run_detail(
    client: Client,
) -> None:
    run = mixed()
    check(run, add_repo(6, stars=4_000), gain=300, verified=False)
    check(run, add_repo(7, stars=300), gain=80, verified=False)

    trending = client.get("/").text
    rising = client.get("/", {"tab": "rising"}).text

    assert "1 ứng viên trending chưa xác minh" in trending
    assert "1 ứng viên đang lên chưa xác minh" in rising
    # Trang chi tiết lượt chỉ liệt kê ứng viên rising chưa xác minh.
    assert f'href="/rising/runs/{run.pk}/#unverified"' in rising
    assert "#unverified" not in trending


def test_hidden_suspicious_count_offers_to_show_them(client: Client) -> None:
    run = report()
    created = timezone.now() - timedelta(days=30)
    fishy = add_repo(1, stars=613, forks=2, created_at=created, pushed_at=created.replace(hour=18))
    check(run, fishy, gain=300, trending=True)

    page = client.get("/").text

    assert "Đã ẩn 1 repo nghi star giả" in page
    assert 'href="/?show_suspicious=on"' in page


def test_filter_form_keeps_tab_and_sort_choices_of_the_tab(client: Client) -> None:
    mixed()

    page = client.get("/", {"tab": "rising", "sort": "gain"}).text

    assert '<input type="hidden" name="tab" value="rising">' in page
    assert '<option value="gain" selected>' in page
    assert '<option value="potential">' in page
    assert '<option value="forks">' not in page  # cách sắp của tab khác


def test_chips_and_clear_all_show_on_the_page(client: Client) -> None:
    mixed()

    page = client.get("/", {"tab": "all", "q": "repo", "min_stars": "100"}).text

    assert "Từ khoá: repo" in page
    assert 'href="/?tab=all&amp;min_stars=100"' in page  # gỡ chip từ khoá
    assert 'href="/?tab=all">Xoá tất cả' in page


def test_report_day_window_uses_utc_days() -> None:
    run = mixed()

    page = services.explore(TRENDING)

    assert page.window_start == WINDOW_END - timedelta(days=6)
    assert page.run == run


def test_more_filters_are_folded_until_one_of_them_is_used(client: Client) -> None:
    mixed()

    plain = client.get("/", {"q": "repo", "sort": "stars"}).text
    grouped = client.get("/", {"aspects": "video"}).text

    assert '<details class="filter-more">' in plain  # chỉ tìm và sắp: phần lọc thêm gập
    assert '<details class="filter-more" open>' in grouped
