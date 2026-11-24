"""Thanh bên có mục Góc nhìn trên mọi trang; góc đang mở được đánh dấu."""

import pytest
from django.test import Client

from features.browse.models import SavedView
from tests.html import nav_links

pytestmark = pytest.mark.django_db

SIDEBAR_VIEWS = "Góc nhìn đã lưu"


def views_in(page: str) -> list[tuple[str, bool]]:
    return [(link.text, link.current) for link in nav_links(page, label=SIDEBAR_VIEWS)]


def test_every_page_lists_saved_views_and_the_manage_link(client: Client) -> None:
    SavedView.objects.create(name="SEO", query="tab=all&q=seo", position=2)
    SavedView.objects.create(name="Video", query="tab=rising&aspects=video", position=1)

    for path in ("/", "/scan/", "/rising/watch/", "/views/"):
        page = client.get(path).text

        assert [text for text, _ in views_in(page)] == ["Video", "SEO", "Quản lý"]


def test_open_view_is_marked_by_its_id_even_after_filters_change(client: Client) -> None:
    video = SavedView.objects.create(name="Video", query="tab=rising&aspects=video")
    SavedView.objects.create(name="SEO", query="tab=all&q=seo")

    page = client.get("/", {"tab": "rising", "q": "khac", "view": str(video.pk)}).text

    assert views_in(page) == [("Video", True), ("SEO", False), ("Quản lý", False)]


def test_filters_equal_to_a_view_mark_it_without_an_id(client: Client) -> None:
    SavedView.objects.create(name="SEO", query="tab=all&q=seo")

    same = client.get("/", {"q": "seo", "tab": "all", "page": "2"}).text
    other = client.get("/", {"q": "seo"}).text
    scan_page = client.get("/scan/").text

    assert views_in(same) == [("SEO", True), ("Quản lý", False)]
    assert views_in(other) == [("SEO", False), ("Quản lý", False)]
    assert views_in(scan_page) == [("SEO", False), ("Quản lý", False)]


def test_saved_view_links_open_the_view_with_its_id(client: Client) -> None:
    view = SavedView.objects.create(name="SEO", query="tab=all&q=seo")

    [link, _manage] = nav_links(client.get("/scan/").text, label=SIDEBAR_VIEWS)

    assert link.href == f"/?tab=all&q=seo&view={view.pk}"


def test_manage_page_marks_manage(client: Client) -> None:
    SavedView.objects.create(name="SEO", query="tab=all&q=seo")

    page = client.get("/views/").text

    assert views_in(page) == [("SEO", False), ("Quản lý", True)]
