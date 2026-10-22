"""Trang web của tính năng Quét — lớp mỏng: nhận yêu cầu → gọi services → hiển thị."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
import respx
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from features.discovery import services
from features.discovery.models import ScanRun
from features.discovery.tests.conftest import (
    DEFAULT_REQUEST,
    REAL_TOP_REPOS,
    SEARCH_URL,
    run_scan_now,
)
from tests.fakes import FakeGitHubSearch, make_search_items

pytestmark = pytest.mark.django_db

UseFake = Callable[[list[dict[str, Any]]], FakeGitHubSearch]
FROM, TO = date(2025, 1, 1), date(2026, 6, 30)
FORM = {"query": "topic:ai-agent", "min_stars": "0", "budget": "50"}


def detail_url(scan: ScanRun) -> str:
    return reverse("discovery:scan_detail", args=[scan.pk])


def many_repos(count: int) -> list[dict[str, Any]]:
    return make_search_items(count, start=FROM, end=TO, stars=lambda i: (i * 7) % 3000)


def test_home_shows_scan_form(client: Client) -> None:
    page = client.get(reverse("discovery:home")).text

    assert 'name="query"' in page
    assert 'name="min_stars"' in page
    assert 'name="budget"' in page
    assert "Chưa có lần quét nào" in page


def test_blank_query_shows_error_and_does_not_scan(client: Client) -> None:
    response = client.post(reverse("discovery:home"), {**FORM, "query": "  "})

    assert response.status_code == 200
    assert "Hãy nhập truy vấn tìm kiếm GitHub." in response.text
    assert ScanRun.objects.count() == 0


def test_post_starts_background_scan_and_redirects(client: Client, use_fake: UseFake) -> None:
    use_fake(many_repos(50))

    response = client.post(reverse("discovery:home"), FORM)

    scan = ScanRun.objects.get()
    assert response.status_code == 302
    assert response["Location"] == detail_url(scan)
    assert scan.status == ScanRun.Status.SUCCEEDED  # luồng nền chạy tại chỗ trong test


def test_post_refused_while_another_scan_is_live(client: Client) -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    response = client.post(reverse("discovery:home"), FORM)

    assert response.status_code == 200
    assert f"Đang chạy lần quét #{live.pk}" in response.text
    assert ScanRun.objects.count() == 1


def test_home_shows_live_scan_and_locks_scan_button(client: Client) -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    page = client.get(reverse("discovery:home")).text

    assert detail_url(live) in page
    assert "disabled" in page


def test_running_scan_page_auto_refreshes(client: Client) -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    page = client.get(detail_url(live)).text

    assert 'http-equiv="refresh"' in page
    assert "Dừng" in page


def test_finished_scan_page_does_not_refresh(client: Client, github_search: respx.Route) -> None:
    scan = run_scan_now()

    page = client.get(detail_url(scan)).text

    assert 'http-equiv="refresh"' not in page


def test_scan_detail_lists_repositories_by_stars(
    client: Client, github_search: respx.Route
) -> None:
    scan = run_scan_now()

    page = client.get(detail_url(scan)).text

    positions = [page.index(name) for name in REAL_TOP_REPOS]
    assert positions == sorted(positions)
    assert "255.793" in page  # số star định dạng kiểu Việt Nam
    assert 'rel="noopener noreferrer"' in page
    assert "40.194" in page  # GitHub báo bao nhiêu — nói thật phần còn thiếu


def test_coverage_and_calls_are_shown(client: Client, use_fake: UseFake) -> None:
    use_fake(many_repos(250))
    scan = run_scan_now(created_from=FROM, created_to=TO, budget=50)

    page = client.get(detail_url(scan)).text

    assert "100%" in page
    assert "3/50" in page  # lượt gọi đã dùng / ngân sách


def test_problem_slices_are_listed(client: Client, use_fake: UseFake) -> None:
    day = date(2026, 1, 5)
    use_fake(make_search_items(1050, start=day, end=day, stars=lambda i: 5))
    scan = run_scan_now(created_from=day, created_to=day, budget=50)

    page = client.get(detail_url(scan)).text

    assert "Bị cắt" in page
    assert "thiếu 50" in page


def test_waiting_time_is_shown(client: Client) -> None:
    live = services.start_scan(DEFAULT_REQUEST)
    until = timezone.now() + timedelta(seconds=60)
    ScanRun.objects.filter(pk=live.pk).update(waiting_until=until)

    page = client.get(detail_url(live)).text

    assert "Đang chờ GitHub tới" in page


def test_failed_scan_shows_reason(client: Client, http_mock: respx.MockRouter) -> None:
    http_mock.get(SEARCH_URL).respond(401, json={"message": "Bad credentials"})
    scan = run_scan_now()

    page = client.get(detail_url(scan)).text

    assert scan.error_message in page


def test_stop_button_requests_stop(client: Client) -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    response = client.post(reverse("discovery:scan_stop", args=[live.pk]))

    live.refresh_from_db()
    assert response.status_code == 302
    assert live.stop_requested is True


def test_resume_runs_remaining_slices(client: Client, use_fake: UseFake) -> None:
    use_fake(many_repos(2500))
    partial = run_scan_now(created_from=FROM, created_to=TO, budget=5)

    response = client.post(
        reverse("discovery:scan_resume", args=[partial.pk]), {"extra_budget": "1000"}
    )

    partial.refresh_from_db()
    assert response.status_code == 302
    assert partial.status == ScanRun.Status.SUCCEEDED
    assert partial.fetched_count == 2500


def test_resume_refused_while_another_scan_is_live(
    client: Client, github_search: respx.Route
) -> None:
    partial = run_scan_now()
    live = services.start_scan(DEFAULT_REQUEST)

    response = client.post(
        reverse("discovery:scan_resume", args=[partial.pk]), {"extra_budget": "50"}
    )

    assert response.status_code == 409
    assert f"Đang chạy lần quét #{live.pk}" in response.text


def test_paused_scan_offers_resume(client: Client, github_search: respx.Route) -> None:
    scan = run_scan_now()

    page = client.get(detail_url(scan)).text

    assert reverse("discovery:scan_resume", args=[scan.pk]) in page
    assert 'name="extra_budget"' in page


@pytest.mark.parametrize("name", ["discovery:scan_stop", "discovery:scan_resume"])
def test_stop_and_resume_require_post(client: Client, name: str) -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    assert client.get(reverse(name, args=[live.pk])).status_code == 405


def test_unknown_scan_returns_404(client: Client) -> None:
    assert client.get(reverse("discovery:scan_detail", args=[999])).status_code == 404


def test_home_lists_recent_scans(client: Client, github_search: respx.Route) -> None:
    run_scan_now(query="topic:ai-video")

    page = client.get(reverse("discovery:home")).text

    assert "topic:ai-video" in page


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github


def test_resume_with_invalid_budget_shows_error(client: Client, github_search: respx.Route) -> None:
    partial = run_scan_now()

    response = client.post(
        reverse("discovery:scan_resume", args=[partial.pk]), {"extra_budget": "7"}
    )

    assert response.status_code == 409
    partial.refresh_from_db()
    assert partial.status == ScanRun.Status.SUCCEEDED_PARTIAL


def test_resume_finished_scan_is_refused(client: Client, github_search: respx.Route) -> None:
    scan = run_scan_now()
    ScanRun.objects.filter(pk=scan.pk).update(status=ScanRun.Status.SUCCEEDED)

    response = client.post(reverse("discovery:scan_resume", args=[scan.pk]), {"extra_budget": "50"})

    assert response.status_code == 409
    assert "không ở trạng thái tiếp tục được" in response.text
