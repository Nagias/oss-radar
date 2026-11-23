"""Khung trang chung (QĐ-20): thanh bên, phông đóng gói sẵn, JS tăng cường, sáng/tối theo máy."""

import pytest
from django.test import Client

from features.discovery.models import ScanRun
from features.rising.models import WatchQuery
from tests.html import nav_links

pytestmark = pytest.mark.django_db

PAGES = [
    "/",
    "/scans/{scan}/",
    "/rising/",
    "/rising/watch/",
    "/rising/watch/{watch}/",
    "/repos/",
]
FONT_PRELOAD = "/static/fonts/be-vietnam-pro/be-vietnam-pro-400-vietnamese.woff2"


def _page(client: Client, path: str) -> str:
    scan = ScanRun.objects.create(query="topic:x", status=ScanRun.Status.SUCCEEDED)
    watch = WatchQuery.objects.create(label="Thử", query="topic:x")
    response = client.get(path.format(scan=scan.pk, watch=watch.pk))
    assert response.status_code == 200
    return response.text


@pytest.mark.parametrize("path", PAGES)
def test_every_page_has_the_sidebar_with_one_current_item(client: Client, path: str) -> None:
    page = _page(client, path)

    assert '<aside class="sidebar"' in page
    links = nav_links(page)
    assert len(links) == 4
    assert len([link for link in links if link.current]) == 1


@pytest.mark.parametrize("path", PAGES)
def test_every_page_loads_app_js_deferred_and_local_fonts(client: Client, path: str) -> None:
    page = _page(client, path)

    assert '<script src="/static/js/app.js" defer></script>' in page
    fonts_at = page.index('<link rel="stylesheet" href="/static/css/fonts.css">')
    assert fonts_at < page.index('<link rel="stylesheet" href="/static/css/app.css">')
    assert (
        f'<link rel="preload" href="{FONT_PRELOAD}" as="font" type="font/woff2" crossorigin>'
        in page
    )


@pytest.mark.parametrize("path", PAGES)
def test_every_page_declares_light_and_dark(client: Client, path: str) -> None:
    page = _page(client, path)

    assert '<meta name="color-scheme" content="light dark">' in page
