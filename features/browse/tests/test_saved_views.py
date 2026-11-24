"""Góc nhìn đã lưu (F-012): lưu bộ lọc của trang Khám phá thành tên, mở lại bằng một bấm."""

from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import Client
from django.urls import reverse

from features.browse.forms import MAX_SAVED_VIEWS
from features.browse.models import SavedView
from tests.html import buttons, forms

pytestmark = pytest.mark.django_db

VIEWS_URL = reverse("browse:views")


def edit_url(view: SavedView) -> str:
    return reverse("browse:view_edit", args=[view.pk])


def delete_url(view: SavedView) -> str:
    return reverse("browse:view_delete", args=[view.pk])


def make_view(
    name: str = "Video cho marketer", query: str = "tab=rising&aspects=video"
) -> SavedView:
    return SavedView.objects.create(name=name, query=query)


def location_query(response: object) -> tuple[str, dict[str, list[str]]]:
    location = urlsplit(response["Location"])  # type: ignore[index]
    return location.path, parse_qs(location.query)


# --- Tạo ------------------------------------------------------------------------------------------


def test_save_stores_the_canonical_query_and_opens_the_view(client: Client) -> None:
    response = client.post(
        VIEWS_URL,
        {
            "name": "  Video cho marketer  ",
            "query": (
                "aspects=video&tab=rising&audience=marketer&audience=creator&page=3&view=9&scan=4"
            ),
        },
    )

    view = SavedView.objects.get()
    assert view.name == "Video cho marketer"
    # Thứ tự cố định, giá trị nhiều lựa chọn đã sắp; bỏ trang, góc nhìn và lần quét.
    assert view.query == "tab=rising&audience=creator&audience=marketer&aspects=video"
    assert response.status_code == 302
    assert location_query(response) == (
        "/",
        {
            "tab": ["rising"],
            "audience": ["creator", "marketer"],
            "aspects": ["video"],
            "view": [str(view.pk)],
        },
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"name": "VIDEO CHO MARKETER", "query": ""}, "Đã có góc nhìn tên"),
        ({"name": "   ", "query": ""}, "Hãy đặt tên cho góc nhìn"),
        ({"name": "x" * 61, "query": ""}, "tối đa 60 ký tự"),
        ({"name": "Lạ", "query": "aspects=khong_co"}, "Bộ lọc không hợp lệ"),
        ({"name": "Âm", "query": "min_stars=-5"}, "Bộ lọc không hợp lệ"),
        ({"name": "Dài", "query": "q=" + "a" * 1000}, "Bộ lọc không hợp lệ"),
    ],
)
def test_save_rejects_bad_input(client: Client, data: dict[str, str], message: str) -> None:
    make_view()

    response = client.post(VIEWS_URL, data)

    assert response.status_code == 400
    assert message in response.text
    assert SavedView.objects.count() == 1


def test_save_refuses_more_than_the_limit(client: Client) -> None:
    SavedView.objects.bulk_create(
        [SavedView(name=f"Góc {number}", query="") for number in range(MAX_SAVED_VIEWS)]
    )

    response = client.post(VIEWS_URL, {"name": "Thêm nữa", "query": "tab=all"})

    assert response.status_code == 400
    assert f"tối đa {MAX_SAVED_VIEWS} góc nhìn" in response.text
    assert SavedView.objects.count() == MAX_SAVED_VIEWS


# --- Đổi tên, cập nhật bộ lọc, xoá ----------------------------------------------------------------


def test_rename_keeps_the_filters(client: Client) -> None:
    view = make_view()

    response = client.post(edit_url(view), {"name": "Video quảng cáo"})

    view.refresh_from_db()
    assert (response.status_code, response["Location"]) == (302, VIEWS_URL)
    assert (view.name, view.query) == ("Video quảng cáo", "tab=rising&aspects=video")


def test_rename_to_another_views_name_is_refused_but_own_case_change_is_fine(
    client: Client,
) -> None:
    view = make_view()
    make_view("SEO", "tab=all&q=seo")

    taken = client.post(edit_url(view), {"name": "seo"})
    own = client.post(edit_url(view), {"name": "VIDEO cho marketer"})

    assert taken.status_code == 400
    assert "Đã có góc nhìn tên" in taken.text
    assert own.status_code == 302
    view.refresh_from_db()
    assert view.name == "VIDEO cho marketer"


def test_update_replaces_the_filters_and_opens_the_view(client: Client) -> None:
    view = make_view()

    response = client.post(edit_url(view), {"query": "q=seo&tab=all&page=2"})

    view.refresh_from_db()
    assert view.query == "tab=all&q=seo"
    assert location_query(response) == (
        "/",
        {"tab": ["all"], "q": ["seo"], "view": [str(view.pk)]},
    )


def test_delete_removes_the_view(client: Client) -> None:
    view = make_view()

    response = client.post(delete_url(view))

    assert (response.status_code, response["Location"]) == (302, VIEWS_URL)
    assert not SavedView.objects.exists()


def test_changes_need_post_and_an_existing_view(client: Client) -> None:
    view = make_view()

    assert client.get(edit_url(view)).status_code == 405
    assert client.get(delete_url(view)).status_code == 405
    assert client.post(reverse("browse:view_edit", args=[999]), {"name": "x"}).status_code == 404
    assert client.post(reverse("browse:view_delete", args=[999])).status_code == 404


# --- Trang quản lý --------------------------------------------------------------------------------


def test_manage_page_lists_views_with_rename_and_confirmed_delete(client: Client) -> None:
    view = make_view()

    page = client.get(VIEWS_URL).text

    assert "Video cho marketer" in page
    assert "Đang lên · Làm được gì: Video &amp; làm phim AI" in page  # tóm tắt bộ lọc
    actions = {form.action: form for form in forms(page) if form.method == "post"}
    assert edit_url(view) in actions
    assert "data-confirm" in actions[delete_url(view)].attrs
    assert {button.text for button in buttons(page)} >= {"Đổi tên", "Xoá"}


def test_manage_page_without_views_explains_how_to_save(client: Client) -> None:
    page = client.get(VIEWS_URL).text

    assert "Chưa có góc nhìn nào" in page
    assert "Lưu góc nhìn" in page


# --- Trên trang Khám phá ----------------------------------------------------------------------


def test_explore_offers_to_save_filters_that_match_no_view(client: Client) -> None:
    make_view()

    page = client.get("/", {"tab": "all", "q": "seo", "page": "2"}).text

    [save] = [form for form in forms(page) if form.action == VIEWS_URL]
    assert [button.text for button in save.buttons] == ["Lưu góc nhìn"]
    assert '<input type="hidden" name="query" value="tab=all&amp;q=seo">' in page


def test_explore_names_the_view_whose_filters_are_shown(client: Client) -> None:
    make_view()

    page = client.get("/", {"tab": "rising", "aspects": "video"}).text

    assert "Đang xem góc nhìn «Video cho marketer»" in page
    assert not [form for form in forms(page) if form.action == VIEWS_URL]


def test_explore_offers_to_update_the_open_view_after_filters_change(client: Client) -> None:
    view = make_view()

    query = {"tab": "rising", "aspects": "video", "q": "ads", "view": str(view.pk)}

    page = client.get("/", query).text

    [update] = [form for form in forms(page) if form.action == edit_url(view)]
    assert [button.text for button in update.buttons] == ["Cập nhật «Video cho marketer»"]
    assert (
        '<input type="hidden" name="query" value="tab=rising&amp;q=ads&amp;aspects=video">' in page
    )
    assert '<input type="hidden" name="view" value="' in page  # đổi lọc tiếp vẫn nhớ góc đang mở
