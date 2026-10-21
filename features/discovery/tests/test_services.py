"""Nghiệp vụ quét: gọi GitHub → ghi kho không trùng → lưu lại lần quét và kết quả của nó."""

from typing import Any

import pytest
import respx

from features.catalog.models import Repository
from features.discovery import services
from features.discovery.models import ScanRun
from features.discovery.tests.conftest import REAL_TOP_REPOS, SEARCH_URL
from tests.factories import load_fixture

pytestmark = pytest.mark.django_db


def test_run_scan_saves_results_and_marks_success(github_search: respx.Route) -> None:
    scan = services.run_scan("topic:ai-agent")

    assert scan.status == ScanRun.Status.SUCCEEDED
    assert scan.total_count == 40194
    assert (scan.fetched_count, scan.created_count, scan.updated_count) == (3, 3, 0)
    assert scan.started_at is not None
    assert scan.finished_at is not None
    assert scan.error_message == ""
    assert Repository.objects.count() == 3
    results = list(services.scan_results(scan))
    assert [r.repository.full_name for r in results] == REAL_TOP_REPOS
    assert all(r.is_new for r in results)


def test_scanning_twice_never_duplicates_repositories(github_search: respx.Route) -> None:
    services.run_scan("topic:ai-agent")

    second = services.run_scan("topic:ai-agent")

    assert Repository.objects.count() == 3
    assert (second.created_count, second.updated_count) == (0, 3)
    assert not any(r.is_new for r in services.scan_results(second))


def test_scan_asks_github_for_one_full_page_sorted_by_stars(github_search: respx.Route) -> None:
    services.run_scan("topic:ai-agent stars:<1000")

    params = github_search.calls.last.request.url.params
    assert params["q"] == "topic:ai-agent stars:<1000"
    assert params["sort"] == "stars"
    assert params["per_page"] == "100"


@pytest.mark.parametrize(
    ("status", "headers", "body", "reason"),
    [
        (403, {"x-ratelimit-remaining": "0"}, {"message": "API rate limit exceeded"}, "hết lượt"),
        (401, {}, {"message": "Bad credentials"}, "GITHUB_TOKEN"),
        (422, {}, load_fixture("github/search_validation_failed.json"), "truy vấn"),
        (502, {}, {"message": "Bad Gateway"}, "Thử lại sau"),
    ],
)
def test_github_failure_marks_scan_failed_with_reason(
    http_mock: respx.MockRouter,
    status: int,
    headers: dict[str, str],
    body: dict[str, Any],
    reason: str,
) -> None:
    http_mock.get(SEARCH_URL).respond(status, headers=headers, json=body)

    scan = services.run_scan("topic:ai-agent")

    assert scan.status == ScanRun.Status.FAILED
    assert reason in scan.error_message
    assert scan.finished_at is not None
    assert Repository.objects.count() == 0


def test_unexpected_error_marks_scan_failed_then_raises(
    github_search: respx.Route, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_upsert(*args: object, **kwargs: object) -> None:
        raise RuntimeError("lỗi lập trình giả lập")

    monkeypatch.setattr(services, "upsert_repositories", broken_upsert)

    with pytest.raises(RuntimeError):
        services.run_scan("topic:ai-agent")

    scan = ScanRun.objects.get()
    assert scan.status == ScanRun.Status.FAILED
    assert "không mong đợi" in scan.error_message
    assert Repository.objects.count() == 0


def test_recent_scans_lists_newest_first(github_search: respx.Route) -> None:
    older = services.run_scan("topic:ai-agent")
    newer = services.run_scan("topic:ai-video")

    assert list(services.recent_scans(limit=1)) == [newer]
    assert list(services.recent_scans()) == [newer, older]


def test_unreadable_github_data_marks_scan_failed(http_mock: respx.MockRouter) -> None:
    http_mock.get(SEARCH_URL).respond(json={"unexpected": True})

    scan = services.run_scan("topic:ai-agent")

    assert scan.status == ScanRun.Status.FAILED
    assert "không đọc được" in scan.error_message


def test_scan_and_result_have_readable_names(github_search: respx.Route) -> None:
    scan = services.run_scan("topic:ai-agent")

    assert str(scan) == f"#{scan.pk} topic:ai-agent"
    assert str(services.scan_results(scan)[0]) == f"#{scan.pk} topic:ai-agent → {REAL_TOP_REPOS[0]}"
