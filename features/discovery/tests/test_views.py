"""Trang web của tính năng Quét: lớp mỏng, chỉ nhận yêu cầu → gọi service → hiển thị."""

import pytest
import respx
from django.test import Client
from django.urls import reverse

from features.discovery import services
from features.discovery.models import ScanRun
from features.discovery.tests.conftest import REAL_TOP_REPOS, SEARCH_URL

pytestmark = pytest.mark.django_db


def test_home_shows_scan_form(client: Client) -> None:
    response = client.get(reverse("discovery:home"))

    assert response.status_code == 200
    assert 'name="query"' in response.text
    assert "Chưa có lần quét nào" in response.text


def test_blank_query_shows_error_and_does_not_scan(client: Client) -> None:
    response = client.post(reverse("discovery:home"), {"query": "  "})

    assert response.status_code == 200
    assert "Hãy nhập truy vấn tìm kiếm GitHub." in response.text
    assert ScanRun.objects.count() == 0


def test_valid_query_scans_then_redirects_to_result(
    client: Client, github_search: respx.Route
) -> None:
    response = client.post(reverse("discovery:home"), {"query": "topic:ai-agent"})

    scan = ScanRun.objects.get()
    assert response.status_code == 302
    assert response["Location"] == reverse("discovery:scan_detail", args=[scan.pk])


def test_scan_detail_lists_repositories_by_stars(
    client: Client, github_search: respx.Route
) -> None:
    scan = services.run_scan("topic:ai-agent")

    page = client.get(reverse("discovery:scan_detail", args=[scan.pk])).text

    positions = [page.index(name) for name in REAL_TOP_REPOS]
    assert positions == sorted(positions)
    assert "255.793" in page  # số star định dạng kiểu Việt Nam
    assert 'rel="noopener noreferrer"' in page


def test_scan_detail_shows_failure_reason(client: Client, http_mock: respx.MockRouter) -> None:
    http_mock.get(SEARCH_URL).respond(401, json={"message": "Bad credentials"})
    scan = services.run_scan("topic:ai-agent")

    page = client.get(reverse("discovery:scan_detail", args=[scan.pk])).text

    assert scan.error_message in page


def test_unknown_scan_returns_404(client: Client) -> None:
    assert client.get(reverse("discovery:scan_detail", args=[999])).status_code == 404


def test_home_lists_recent_scans(client: Client, github_search: respx.Route) -> None:
    services.run_scan("topic:ai-video")

    page = client.get(reverse("discovery:home")).text

    assert "topic:ai-video" in page
