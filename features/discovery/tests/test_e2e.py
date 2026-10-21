"""Kiểm chứng tự động cho bộ khung đi được F-001 — đi đúng đường người dùng đi.

Người dùng mở trang → gõ truy vấn → bấm Quét → thấy repo sắp theo star, đánh dấu Mới →
quét lại lần nữa → không có dòng trùng, repo đã biết được đánh dấu Đã có.
Chỉ GitHub là giả lập (bằng phản hồi thật đã lưu); mọi lớp còn lại chạy thật, kể cả CSDL.
"""

import pytest
import respx
from django.test import Client
from django.urls import reverse

from features.catalog.models import Repository
from features.discovery.tests.conftest import REAL_TOP_REPOS

pytestmark = pytest.mark.django_db


def test_walking_skeleton_scan_store_show_without_duplicates(
    client: Client, github_search: respx.Route
) -> None:
    home = client.get(reverse("discovery:home"))
    assert home.status_code == 200

    first = client.post(reverse("discovery:home"), {"query": "topic:ai-agent"}, follow=True)

    page = first.text
    assert first.status_code == 200
    assert [page.index(name) for name in REAL_TOP_REPOS] == sorted(
        page.index(name) for name in REAL_TOP_REPOS
    )
    assert page.count("badge-new") == 3
    assert "40.194" in page  # GitHub báo tổng nhiều hơn số đã lấy → có cảnh báo
    assert Repository.objects.count() == 3

    second = client.post(reverse("discovery:home"), {"query": "topic:ai-agent"}, follow=True)

    assert Repository.objects.count() == 3
    assert second.text.count("badge-known") == 3
    assert "badge-new" not in second.text
    assert github_search.call_count == 2
