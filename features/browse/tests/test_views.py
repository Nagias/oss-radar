"""Trang Kho repo `/repos/`: ô lọc lấy từ địa chỉ trang, ô sai không hỏng trang, link an toàn."""

import pytest
from django.test import Client
from django.urls import reverse

from features.browse.forms import BrowseForm
from features.browse.services import BrowseFilters
from features.browse.tests.conftest import add_repo, label

pytestmark = pytest.mark.django_db

URL = reverse("browse:repos")


def test_page_lists_repos_with_labels_scores_and_safe_links(client: Client) -> None:
    repo = add_repo(1, description="<script>alert(1)</script>")
    label(repo, audience=("creator",), aspects=("video",))

    page = client.get(URL).text

    assert (
        '<a href="https://github.com/chu/repo-1" target="_blank" rel="noopener noreferrer">' in page
    )
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert "Nhà sáng tạo nội dung (video, YouTube, ảnh)" in page
    assert f'href="{URL}?audience=creator"' in page  # bấm nhãn = lọc theo nhãn đó
    assert 'title="lý do 1"' in page
    assert "Phổ biến <strong>" in page  # điểm Chất lượng mở được từng thành phần
    assert "1 repo" in page


def test_filters_come_from_query_string_and_are_kept_in_form(client: Client) -> None:
    video = add_repo(1, stars=500)
    label(video, audience=("creator",), aspects=("video",))
    add_repo(2, stars=900)

    page = client.get(URL, {"aspects": "video", "sort": "forks", "min_stars": "100"}).text

    assert "chu/repo-1" in page
    assert "chu/repo-2" not in page
    assert 'value="video" checked' in page
    assert '<option value="forks" selected>' in page
    assert 'name="min_stars" value="100"' in page


def test_bad_values_fall_back_to_defaults_without_error(client: Client) -> None:
    add_repo(1)

    response = client.get(
        URL,
        {"page": "abc", "min_stars": "-1", "aspects": "khong_co", "sort": "lung_tung", "scan": "x"},
    )

    assert response.status_code == 200
    assert "chu/repo-1" in response.text


def test_pagination_links_keep_filters(client: Client) -> None:
    for github_id in range(1, 53):
        add_repo(github_id, stars=1000 - github_id, language="Go")

    page = client.get(URL, {"language": "Go"}).text

    assert "Trang 1/2" in page
    assert f'href="{URL}?language=Go&amp;page=2"' in page


def test_empty_result_says_so(client: Client) -> None:
    page = client.get(URL, {"q": "khong-ton-tai"}).text

    assert "Không có repo nào khớp bộ lọc" in page


def test_nav_has_link_to_browse(client: Client) -> None:
    page = client.get(reverse("discovery:home")).text

    assert f'href="{URL}"' in page


def test_form_filters_keep_valid_fields_when_others_are_wrong() -> None:
    form = BrowseForm(
        {
            "audience": ["creator", "lung_tung"],
            "aspects": ["video"],
            "min_stars": "-5",
            "max_stars": "1000",
            "rising_only": "on",
            "page": "0",
        }
    )

    filters = form.filters()

    assert filters.audience == ()  # có mã lạ → cả ô bị coi là sai → không lọc ô đó
    assert filters.aspects == ("video",)
    assert (filters.min_stars, filters.max_stars) == (None, 1000)
    assert filters.rising_only is True
    assert filters.page == 1
    assert BrowseForm().filters() == BrowseFilters()
