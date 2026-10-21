"""Test gọi GitHub THẬT qua Internet — chỉ chạy bằng `uv run poe test-live`, không chạy trong CI.

Mục đích: phát hiện sớm khi GitHub đổi định dạng phản hồi mà dữ liệu giả lập đã lưu không còn đúng.
Mỗi lần chạy tốn 2 lượt tìm kiếm của GitHub.
"""

import pytest

from features.catalog.models import Repository
from features.discovery import services
from features.discovery.models import ScanRun
from integrations.github.client import get_github_client

pytestmark = pytest.mark.live


def test_live_search_returns_repositories_sorted_by_stars() -> None:
    with get_github_client() as github:
        page = github.search_repositories("topic:ai-agent", per_page=5)

    assert page.total_count > 0
    assert len(page.items) == 5
    stars = [repo.stars for repo in page.items]
    assert stars == sorted(stars, reverse=True)
    assert all(repo.html_url.startswith("https://github.com/") for repo in page.items)


@pytest.mark.django_db
def test_live_scan_stores_first_page_without_duplicates() -> None:
    scan = services.run_scan("topic:ai-agent")

    assert scan.status == ScanRun.Status.SUCCEEDED, scan.error_message
    assert scan.fetched_count > 0
    assert Repository.objects.count() == scan.fetched_count
