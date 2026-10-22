"""Test gọi GitHub THẬT qua Internet — chỉ chạy bằng `uv run poe test-live`, không chạy trong CI.

Mục đích: phát hiện sớm khi GitHub đổi định dạng phản hồi hoặc cú pháp truy vấn, làm dữ liệu
giả lập đã lưu không còn đúng. Mỗi lần chạy tốn tối đa 4 lượt tìm kiếm (giãn nhịp thật) và
1 lượt lấy lịch sử star (tính vào hạn mức "core", không cần token).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

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


def test_live_star_history_by_id() -> None:
    # 42976210 là repo star-history; tra theo id nên không phụ thuộc việc repo đổi tên.
    with get_github_client() as github:
        history = github.star_history(42976210, weeks=2)

    assert len(history.weeks) == 2
    newest, previous = history.weeks
    assert newest.start.weekday() == 6  # Chủ nhật
    assert newest.start - previous.start == timedelta(days=7)
    assert 0 <= (timezone.now().date() - newest.start).days <= 6  # tuần mới nhất là tuần này
    assert all(len(week.days) == 7 and min(week.days) >= 0 for week in history.weeks)


@pytest.mark.django_db
def test_live_deep_scan_within_small_budget_without_duplicates() -> None:
    today = timezone.localdate()
    scan = services.start_scan(
        services.ScanRequest(
            query="topic:ai-video",
            min_stars=10,
            max_stars=None,
            created_from=today - timedelta(days=60),
            created_to=today,
            budget=3,
        )
    )

    services.execute_scan(scan.pk)
    scan.refresh_from_db()

    assert scan.status in (ScanRun.Status.SUCCEEDED, ScanRun.Status.SUCCEEDED_PARTIAL), (
        scan.error_message or scan.stop_reason
    )
    assert scan.api_calls_used <= 3
    assert scan.total_count is not None
    assert Repository.objects.count() == scan.fetched_count
    assert all(stars >= 10 for stars in Repository.objects.values_list("stars", flat=True))
