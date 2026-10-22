"""Kiểm chứng tự động cho F-001 + F-002 — đi đúng đường người dùng đi trên trang web.

Mở trang → gõ truy vấn, chọn mức Sâu → bấm Quét → luồng nền quét ĐỦ (vượt trần 1.000 bằng chia lát)
→ trang kết quả độ phủ 100%, sắp theo star → quét lại → không có dòng trùng.
Chỉ GitHub là giả lập (bằng khuôn phản hồi thật); mọi lớp còn lại chạy thật, kể cả CSDL.
"""

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from features.catalog.models import Repository
from features.discovery.models import ScanRun
from tests.fakes import FakeGitHubSearch, make_search_items

pytestmark = pytest.mark.django_db


def test_deep_scan_from_browser_gets_everything_without_duplicates(
    client: Client,
    use_fake_github: Callable[[list[dict[str, Any]]], FakeGitHubSearch],
) -> None:
    items = make_search_items(
        1500, start=date(2025, 1, 1), end=date(2026, 6, 30), stars=lambda i: 2000 - i
    )
    use_fake_github(items)
    form = {
        "query": "topic:ai-agent",
        "min_stars": "0",
        "created_from": "2025-01-01",
        "created_to": "2026-06-30",
        "budget": "300",
    }
    assert client.get(reverse("discovery:home")).status_code == 200

    first = client.post(reverse("discovery:home"), form, follow=True)

    page = first.text
    assert ScanRun.objects.get().status == ScanRun.Status.SUCCEEDED
    assert "100%" in page
    assert "1.500" in page
    top = [page.index(f"gia-lap/repo-{repo_id}<") for repo_id in (1, 2, 3)]
    assert top == sorted(top)  # repo-1 có nhiều star nhất, rồi repo-2, repo-3
    assert Repository.objects.count() == 1500

    second = client.post(reverse("discovery:home"), form, follow=True)

    assert Repository.objects.count() == 1500
    assert "badge-new" not in second.text
