"""Nghiệp vụ quét: bắt đầu, chạy, dừng, tiếp tục; mỗi lúc một lần quét; lỗi nói rõ tiếng Việt."""

from datetime import timedelta
from typing import Any

import pytest
import respx
from django.utils import timezone

from features.catalog.models import Repository
from features.discovery import services
from features.discovery.models import ScanRun, ScanSlice
from features.discovery.tests.conftest import (
    DEFAULT_REQUEST,
    REAL_TOP_REPOS,
    SEARCH_URL,
    run_scan_now,
)
from tests.factories import load_fixture
from tests.fakes import FakeTime

pytestmark = pytest.mark.django_db


def make_stale(scan: ScanRun) -> None:
    ScanRun.objects.filter(pk=scan.pk).update(heartbeat_at=timezone.now() - timedelta(minutes=3))


# --- Mức Nhanh (= quét của F-001) ------------------------------------------------------------


def test_quick_scan_takes_first_page_and_says_what_is_left(github_search: respx.Route) -> None:
    scan = run_scan_now()

    assert scan.status == ScanRun.Status.SUCCEEDED_PARTIAL
    assert "ngân sách" in scan.stop_reason
    assert (scan.total_count, scan.fetched_count, scan.created_count) == (40194, 3, 3)
    assert scan.api_calls_used == 1
    results = list(services.scan_results(scan))
    assert [r.repository.full_name for r in results] == REAL_TOP_REPOS
    assert all(r.is_new for r in results)


def test_scanning_twice_never_duplicates_repositories(github_search: respx.Route) -> None:
    run_scan_now()

    second = run_scan_now()

    assert Repository.objects.count() == 3
    assert (second.created_count, second.updated_count) == (0, 3)
    assert not any(r.is_new for r in services.scan_results(second))


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (401, {"message": "Bad credentials"}, "GITHUB_TOKEN"),
        (422, load_fixture("github/search_validation_failed.json"), "truy vấn"),
    ],
)
def test_unrecoverable_github_error_fails_scan_with_reason(
    http_mock: respx.MockRouter, status: int, body: dict[str, Any], reason: str
) -> None:
    http_mock.get(SEARCH_URL).respond(status, json=body)

    scan = run_scan_now()

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
        run_scan_now()

    scan = ScanRun.objects.get()
    assert scan.status == ScanRun.Status.FAILED
    assert "không mong đợi" in scan.error_message
    assert Repository.objects.count() == 0


# --- Mỗi lúc một lần quét; phát hiện gián đoạn ------------------------------------------------


def test_start_refused_while_another_scan_is_live() -> None:
    first = services.start_scan(DEFAULT_REQUEST)

    with pytest.raises(services.ScanAlreadyRunningError) as caught:
        services.start_scan(DEFAULT_REQUEST)

    assert caught.value.scan == first
    assert services.live_scan() == first


def test_stale_running_scan_becomes_paused_interrupted() -> None:
    first = services.start_scan(DEFAULT_REQUEST)
    make_stale(first)

    second = services.start_scan(DEFAULT_REQUEST)

    first.refresh_from_db()
    assert first.status == ScanRun.Status.PAUSED
    assert "gián đoạn" in first.stop_reason
    assert services.live_scan() == second


def test_resume_refused_while_another_scan_is_live() -> None:
    first = services.start_scan(DEFAULT_REQUEST)
    make_stale(first)
    services.pause_stale_scans()
    services.start_scan(DEFAULT_REQUEST)
    first.refresh_from_db()

    with pytest.raises(services.ScanAlreadyRunningError):
        services.resume_scan(first, extra_budget=50)


def test_resume_resets_only_failed_and_incomplete_slices() -> None:
    scan = services.start_scan(DEFAULT_REQUEST)
    ScanRun.objects.filter(pk=scan.pk).update(status=ScanRun.Status.PAUSED)
    root = scan.slices.get()
    statuses = [
        ScanSlice.Status.DONE,
        ScanSlice.Status.FAILED,
        ScanSlice.Status.INCOMPLETE,
        ScanSlice.Status.TRUNCATED,
    ]
    for order, status in enumerate(statuses, start=2):
        ScanSlice.objects.create(
            scan_run=scan,
            stack_order=order,
            created_from=root.created_from,
            created_to=root.created_to,
            stars_min=0,
            status=status,
            retried_incomplete=True,
        )
    scan.refresh_from_db()

    services.resume_scan(scan, extra_budget=50)

    scan.refresh_from_db()
    assert scan.status == ScanRun.Status.RUNNING
    assert scan.budget == 51
    by_order = dict(scan.slices.values_list("stack_order", "status"))
    assert by_order[2] == ScanSlice.Status.DONE
    assert by_order[3] == ScanSlice.Status.PENDING
    assert by_order[4] == ScanSlice.Status.PENDING
    assert by_order[5] == ScanSlice.Status.TRUNCATED


def test_resume_refuses_finished_scan(github_search: respx.Route) -> None:
    scan = run_scan_now()
    ScanRun.objects.filter(pk=scan.pk).update(status=ScanRun.Status.SUCCEEDED)
    scan.refresh_from_db()

    with pytest.raises(ValueError, match="không"):
        services.resume_scan(scan, extra_budget=50)


# --- Nhịp sống khi phải chờ lâu ---------------------------------------------------------------


def test_heartbeat_sleeper_beats_in_chunks_and_clears_wait(fake_time: FakeTime) -> None:
    scan = services.start_scan(DEFAULT_REQUEST)
    make_stale(scan)

    services.HeartbeatSleeper(scan.pk, chunk=10.0)(25.0)

    scan.refresh_from_db()
    assert fake_time.sleeps == [10.0, 10.0, 5.0]
    assert scan.is_live
    assert scan.waiting_until is None


def test_heartbeat_sleeper_shows_long_wait_while_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    scan = services.start_scan(DEFAULT_REQUEST)
    seen: list[object] = []
    monkeypatch.setattr(
        "time.sleep",
        lambda seconds: seen.append(ScanRun.objects.get(pk=scan.pk).waiting_until),
    )

    services.HeartbeatSleeper(scan.pk)(30.0)

    assert seen
    assert all(value is not None for value in seen)


def test_heartbeat_sleeper_honours_stop_request() -> None:
    scan = services.start_scan(DEFAULT_REQUEST)
    services.request_stop(scan)

    with pytest.raises(services.StopRequestedError):
        services.HeartbeatSleeper(scan.pk)(1.0)


# --- Truy vấn danh sách -----------------------------------------------------------------------


def test_recent_scans_lists_newest_first(github_search: respx.Route) -> None:
    older = run_scan_now()
    newer = run_scan_now(query="topic:ai-video")

    assert list(services.recent_scans(limit=1)) == [newer]
    assert list(services.recent_scans()) == [newer, older]


def test_coverage_percent() -> None:
    scan = ScanRun(query="x")
    assert scan.coverage_percent is None
    scan.total_count, scan.fetched_count = 0, 0
    assert scan.coverage_percent == 100.0
    scan.total_count, scan.fetched_count = 3, 1
    assert scan.coverage_percent == 33.3


def test_scan_slice_and_result_have_readable_names(github_search: respx.Route) -> None:
    scan = run_scan_now()

    assert str(scan) == f"#{scan.pk} topic:ai-agent"
    assert str(services.scan_results(scan)[0]) == f"#{scan.pk} topic:ai-agent → {REAL_TOP_REPOS[0]}"
    assert "2008-01-01" in str(scan.slices.get(stack_order=1))
