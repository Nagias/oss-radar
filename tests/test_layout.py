"""Khung trang chung (QĐ-20): thanh bên, phông đóng gói sẵn, JS tăng cường, sáng/tối theo máy."""

import re

import pytest
from django.test import Client

from features.discovery.models import ScanRun
from features.rising.models import WatchQuery
from features.rising.tests.conftest import make_run
from tests.html import forms, nav_links

pytestmark = pytest.mark.django_db

PAGES = [
    "/",
    "/scan/",
    "/scans/{scan}/",
    "/rising/runs/{run}/",
    "/rising/watch/",
    "/rising/watch/{watch}/",
]
FONT_PRELOAD = "/static/fonts/be-vietnam-pro/be-vietnam-pro-400-vietnamese.woff2"


def _page(client: Client, path: str) -> str:
    scan = ScanRun.objects.create(query="topic:x", status=ScanRun.Status.SUCCEEDED)
    watch = WatchQuery.objects.create(label="Thử", query="topic:x")
    run = make_run()  # có báo cáo để trang chi tiết lượt hiện đủ bảng và bộ lọc
    response = client.get(path.format(scan=scan.pk, watch=watch.pk, run=run.pk))
    assert response.status_code == 200
    return response.text


@pytest.mark.parametrize("path", PAGES)
def test_every_page_has_the_sidebar_with_one_current_item(client: Client, path: str) -> None:
    page = _page(client, path)

    assert '<aside class="sidebar"' in page
    links = nav_links(page)
    assert len(links) == 3
    assert len([link for link in links if link.current]) == 1


@pytest.mark.parametrize("path", PAGES)
def test_every_page_loads_app_js_deferred_and_local_fonts(client: Client, path: str) -> None:
    page = _page(client, path)

    assert re.search(r'<script src="/static/js/app\.js\?v=[\w.-]+" defer></script>', page)
    fonts = re.search(r'<link rel="stylesheet" href="/static/css/fonts\.css\?v=[\w.-]+">', page)
    app_css = re.search(r'<link rel="stylesheet" href="/static/css/app\.css\?v=[\w.-]+">', page)
    assert fonts
    assert app_css
    assert fonts.start() < app_css.start()
    assert (
        f'<link rel="preload" href="{FONT_PRELOAD}" as="font" type="font/woff2" crossorigin>'
        in page
    )


@pytest.mark.parametrize("path", PAGES)
def test_every_page_declares_light_and_dark(client: Client, path: str) -> None:
    page = _page(client, path)

    assert '<meta name="color-scheme" content="light dark">' in page


@pytest.mark.parametrize("path", PAGES)
def test_autosubmit_forms_keep_a_submit_button(client: Client, path: str) -> None:
    # Tắt JS thì form không tự gửi: phải còn nút để bấm lọc.
    page = _page(client, path)

    for form in forms(page):
        if "data-autosubmit" in form.attrs:
            assert form.buttons, f"Form tự gửi {form.action} không có nút gửi"


@pytest.mark.parametrize("path", ["/rising/runs/{run}/", "/"])
def test_filter_forms_submit_on_change(client: Client, path: str) -> None:
    page = _page(client, path)

    filters = [form for form in forms(page) if form.method == "get"]
    assert filters
    assert all("data-autosubmit" in form.attrs for form in filters)
    assert all("data-clean-query" in form.attrs for form in filters)


def test_browse_search_box_is_marked_for_the_slash_shortcut(client: Client) -> None:
    page = _page(client, "/")

    assert re.search(r'<input[^>]*name="q"[^>]*data-search', page)


@pytest.mark.parametrize(
    ("path", "title"),
    [
        ("/", "Khám phá"),
        ("/scan/", "Quét GitHub theo truy vấn"),
        ("/rising/runs/{run}/", "Báo cáo lượt quét ngày 22/10/2026"),
        ("/rising/watch/", "Danh sách theo dõi"),
        ("/rising/watch/{watch}/", "Sửa truy vấn theo dõi"),
    ],
)
def test_every_page_header_shows_its_title_and_intro(client: Client, path: str, title: str) -> None:
    page = _page(client, path)

    header = re.search(r'<header class="page-header">\s*<h1>(.*?)</h1>\s*<p>(.*?)</p>', page, re.S)
    assert header, "Thiếu phần đầu trang"
    assert header.group(1).strip() == title
    assert len(header.group(2).split()) >= 8, "Đoạn giới thiệu trống hoặc hỏng"
