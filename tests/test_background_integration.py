"""Luồng nền THẬT + CSDL thật (không chạy tại chỗ như test của tính năng): kết nối CSDL riêng mỗi
luồng, đóng kết nối sau việc, transaction IMMEDIATE — đúng đường app chạy ngoài đời."""

import pytest
import respx

from core import background
from features.discovery import services
from features.discovery.models import ScanRun
from tests.factories import load_fixture

pytestmark = pytest.mark.django_db(transaction=True)

SEARCH_URL = "https://api.github.com/search/repositories"


def test_scan_runs_on_real_background_thread(http_mock: respx.MockRouter) -> None:
    http_mock.get(SEARCH_URL).respond(json=load_fixture("github/search_repositories.json"))
    scan = services.start_scan(
        services.ScanRequest("topic:ai-agent", 0, None, None, None, budget=1)
    )

    background.submit(services.execute_scan, scan.pk).result(timeout=30)

    scan.refresh_from_db()
    assert scan.status == ScanRun.Status.SUCCEEDED_PARTIAL
    assert (scan.fetched_count, scan.api_calls_used) == (3, 1)
    assert services.live_scan() is None
