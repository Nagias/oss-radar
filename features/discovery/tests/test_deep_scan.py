"""Quét sâu: lấy ĐỦ repo vượt trần 1.000 kết quả, trong ngân sách, bền trước lỗi, độ phủ thật."""

from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest
import respx

from features.catalog.models import Repository
from features.discovery import services
from features.discovery.models import ScanRun, ScanSlice
from features.discovery.tests.conftest import SEARCH_URL, run_scan_now
from tests.fakes import FakeGitHubSearch, FakeTime, make_search_items

pytestmark = pytest.mark.django_db

UseFake = Callable[[list[dict[str, Any]]], FakeGitHubSearch]

FROM, TO = date(2025, 1, 1), date(2026, 6, 30)
NEWER_HALF_STARTS = date(2025, 10, 1)  # 2025-01-01 + 545 ngày // 2 = 2025-09-30 → nửa mới từ 10-01


def many_repos(count: int = 2500) -> list[dict[str, Any]]:
    return make_search_items(count, start=FROM, end=TO, stars=lambda i: (i * 7) % 3000)


def deep(**overrides: Any) -> ScanRun:
    params: dict[str, Any] = {"created_from": FROM, "created_to": TO, "budget": 1000}
    params.update(overrides)
    return run_scan_now(**params)


def fetched_ids(scan: ScanRun) -> set[int]:
    return set(scan.results.values_list("repository__github_id", flat=True))


def test_under_1000_fetches_all_pages_and_finishes(use_fake: UseFake) -> None:
    use_fake(many_repos(250))

    scan = deep()

    assert scan.status == ScanRun.Status.SUCCEEDED
    assert (scan.total_count, scan.fetched_count, scan.api_calls_used) == (250, 250, 3)
    assert scan.coverage_percent == 100.0
    assert list(scan.slices.values_list("status", flat=True)) == [ScanSlice.Status.DONE]


def test_over_1000_splits_by_date_until_full_coverage(use_fake: UseFake) -> None:
    fake = use_fake(many_repos())

    scan = deep()

    assert scan.status == ScanRun.Status.SUCCEEDED
    assert scan.fetched_count == 2500
    assert Repository.objects.count() == 2500
    assert scan.coverage_percent == 100.0
    done = scan.slices.filter(status=ScanSlice.Status.DONE)
    assert all(s.total_count is not None and s.total_count <= 1000 for s in done)
    assert all(query.count("stars:") == 1 for query in fake.queries)


def test_newest_slices_are_processed_first_when_budget_runs_out(use_fake: UseFake) -> None:
    use_fake(many_repos())

    scan = deep(budget=4)

    assert scan.status == ScanRun.Status.SUCCEEDED_PARTIAL
    assert "ngân sách" in scan.stop_reason
    assert scan.api_calls_used == 4
    worked = scan.slices.exclude(stack_order=1).filter(pages_fetched__gt=0)
    assert worked.exists()
    assert all(s.created_from >= NEWER_HALF_STARTS for s in worked)


def test_single_day_burst_is_split_by_stars(use_fake: UseFake) -> None:
    day = date(2026, 1, 5)
    use_fake(make_search_items(1200, start=day, end=day, stars=lambda i: i))

    scan = deep(created_from=day, created_to=day)

    assert scan.status == ScanRun.Status.SUCCEEDED
    assert scan.fetched_count == 1200
    assert scan.slices.filter(stars_max__isnull=False).exists()


def test_same_day_same_stars_over_1000_is_truncated(use_fake: UseFake) -> None:
    day = date(2026, 1, 5)
    use_fake(make_search_items(1050, start=day, end=day, stars=lambda i: 5))

    scan = deep(created_from=day, created_to=day)

    assert scan.status == ScanRun.Status.SUCCEEDED_PARTIAL
    assert scan.fetched_count == 1000
    truncated = scan.slices.get(status=ScanSlice.Status.TRUNCATED)
    assert "1.000" in truncated.error_message
    assert list(services.problem_slices(scan)) == [truncated]


def test_star_bounds_filter_results(use_fake: UseFake) -> None:
    items = make_search_items(300, start=FROM, end=TO, stars=lambda i: i * 7)
    use_fake(items)
    expected = sum(1 for it in items if 100 <= it["stargazers_count"] <= 999)

    scan = deep(min_stars=100, max_stars=999)

    assert scan.fetched_count == expected
    stars = Repository.objects.values_list("stars", flat=True)
    assert all(100 <= value <= 999 for value in stars)


def test_zero_results_finishes_with_full_coverage(use_fake: UseFake) -> None:
    use_fake([])

    scan = deep()

    assert scan.status == ScanRun.Status.SUCCEEDED
    assert (scan.total_count, scan.fetched_count, scan.api_calls_used) == (0, 0, 1)
    assert scan.coverage_percent == 100.0


def test_short_page_before_expected_total_is_not_trusted(http_mock: respx.MockRouter) -> None:
    template = make_search_items(120, start=FROM, end=FROM, stars=lambda i: 1000 - i)

    def lying_github(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        items = template[:100] if page == 1 else template[100:120]
        return httpx.Response(
            200, json={"total_count": 250, "incomplete_results": False, "items": items}
        )

    route = http_mock.get(SEARCH_URL).mock(side_effect=lying_github)

    scan = deep()

    assert route.call_count == 4  # trang 1, 2 rồi làm lại lát 1 lần; không bao giờ hỏi trang 3
    assert all(call.request.url.params["page"] in {"1", "2"} for call in route.calls)
    assert scan.slices.get().status == ScanSlice.Status.INCOMPLETE
    assert scan.status == ScanRun.Status.SUCCEEDED_PARTIAL


def test_budget_exhausted_then_resume_matches_uninterrupted_run(use_fake: UseFake) -> None:
    use_fake(many_repos())
    uninterrupted = deep()

    partial = deep(budget=5)
    assert partial.status == ScanRun.Status.SUCCEEDED_PARTIAL
    services.resume_scan(partial, extra_budget=1000)
    services.execute_scan(partial.pk)
    partial.refresh_from_db()

    assert partial.status == ScanRun.Status.SUCCEEDED
    assert fetched_ids(partial) == fetched_ids(uninterrupted)
    assert partial.results.count() == partial.fetched_count == 2500


def test_failed_slice_does_not_stop_others_and_resume_fixes_it(use_fake: UseFake) -> None:
    fake = use_fake(many_repos())
    older_half = "created:2025-01-01..2025-09-30"
    fake.fail_when = lambda q: 502 if older_half in q else None

    scan = deep()

    assert scan.status == ScanRun.Status.SUCCEEDED_PARTIAL
    failed = scan.slices.get(status=ScanSlice.Status.FAILED)
    assert failed.created_to == date(2025, 9, 30)
    assert "Thử lại sau" in failed.error_message
    assert scan.slices.filter(status=ScanSlice.Status.DONE).exists()

    fake.fail_when = None
    services.resume_scan(scan, extra_budget=1000)
    services.execute_scan(scan.pk)
    scan.refresh_from_db()
    assert scan.status == ScanRun.Status.SUCCEEDED
    assert scan.fetched_count == 2500


def test_three_failed_slices_in_a_row_pause_scan(use_fake: UseFake) -> None:
    fake = use_fake(many_repos())
    fake.fail_when = lambda q: None if len(fake.queries) <= 2 else 502

    scan = deep()

    assert scan.status == ScanRun.Status.PAUSED
    assert "Mất kết nối" in scan.stop_reason
    assert scan.slices.filter(status=ScanSlice.Status.FAILED).count() == 3


def test_auth_error_fails_whole_scan(http_mock: respx.MockRouter) -> None:
    http_mock.get(SEARCH_URL).respond(401, json={"message": "Bad credentials"})

    scan = deep()

    assert scan.status == ScanRun.Status.FAILED
    assert "GITHUB_TOKEN" in scan.error_message
    assert scan.api_calls_used == 1


def test_long_rate_limit_wait_pauses_scan(http_mock: respx.MockRouter, fake_time: FakeTime) -> None:
    reset = str(int(fake_time.time()) + 3600)
    http_mock.get(SEARCH_URL).respond(
        403,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset},
        json={"message": "API rate limit exceeded"},
    )

    scan = deep()

    assert scan.status == ScanRun.Status.PAUSED
    assert "chờ" in scan.stop_reason


def test_incomplete_results_are_retried_once(use_fake: UseFake) -> None:
    fake = use_fake(many_repos(250))
    fake.incomplete_when = lambda q: len(fake.queries) == 1

    scan = deep()

    assert scan.status == ScanRun.Status.SUCCEEDED
    assert scan.api_calls_used == 6  # 3 trang, làm lại lát 1 lần


def test_always_incomplete_results_marked_not_sure(use_fake: UseFake) -> None:
    fake = use_fake(many_repos(250))
    fake.incomplete_when = lambda q: True

    scan = deep()

    assert scan.status == ScanRun.Status.SUCCEEDED_PARTIAL
    assert scan.slices.get().status == ScanSlice.Status.INCOMPLETE


def test_stop_request_pauses_scan_before_next_call(use_fake: UseFake) -> None:
    use_fake(many_repos())
    scan = services.start_scan(
        services.ScanRequest("topic:ai-agent", 0, None, FROM, TO, budget=1000)
    )
    services.request_stop(scan)

    services.execute_scan(scan.pk)
    scan.refresh_from_db()

    assert scan.status == ScanRun.Status.PAUSED
    assert "Dừng" in scan.stop_reason
    assert scan.api_calls_used == 0


def test_retries_count_against_budget(use_fake: UseFake) -> None:
    fake = use_fake(many_repos(50))
    fake.fail_when = lambda q: 502 if len(fake.queries) <= 2 else None

    scan = deep()

    assert scan.status == ScanRun.Status.SUCCEEDED
    assert scan.api_calls_used == 3


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github


def test_runner_stops_when_scan_is_paused_from_elsewhere(use_fake: UseFake) -> None:
    fake = use_fake(many_repos())
    scan = services.start_scan(
        services.ScanRequest("topic:ai-agent", 0, None, FROM, TO, budget=1000)
    )

    def pause_from_elsewhere(query: str) -> None:
        if len(fake.queries) == 2:
            ScanRun.objects.filter(pk=scan.pk).update(
                status=ScanRun.Status.PAUSED, stop_reason="bị gián đoạn (giả lập)"
            )

    fake.on_query = pause_from_elsewhere

    services.execute_scan(scan.pk)

    scan.refresh_from_db()
    assert scan.status == ScanRun.Status.PAUSED
    assert scan.stop_reason == "bị gián đoạn (giả lập)"
    assert len(fake.queries) <= 3


def test_stale_runner_cannot_overwrite_a_resumed_scan(use_fake: UseFake) -> None:
    fake = use_fake(many_repos())
    scan = services.start_scan(
        services.ScanRequest("topic:ai-agent", 0, None, FROM, TO, budget=1000)
    )

    def paused_then_resumed_elsewhere(query: str) -> None:
        if len(fake.queries) == 2:
            ScanRun.objects.filter(pk=scan.pk).update(status=ScanRun.Status.PAUSED)
            services.resume_scan(ScanRun.objects.get(pk=scan.pk), extra_budget=50)

    fake.on_query = paused_then_resumed_elsewhere

    services.execute_scan(scan.pk)  # luồng cũ chạy tiếp như "xác sống"

    scan.refresh_from_db()
    assert scan.status == ScanRun.Status.RUNNING  # lần Tiếp tục vẫn nguyên, chưa bị ghi đè
    assert scan.budget == 1050


def test_ctrl_c_pauses_scan_instead_of_leaving_it_running(use_fake: UseFake) -> None:
    fake = use_fake(many_repos())
    scan = services.start_scan(
        services.ScanRequest("topic:ai-agent", 0, None, FROM, TO, budget=1000)
    )

    def user_presses_ctrl_c(query: str) -> None:
        if len(fake.queries) == 2:
            raise KeyboardInterrupt

    fake.on_query = user_presses_ctrl_c

    with pytest.raises(KeyboardInterrupt):
        services.execute_scan(scan.pk)

    scan.refresh_from_db()
    assert scan.status == ScanRun.Status.PAUSED
    assert "Tiếp tục" in scan.stop_reason


def test_progress_is_logged_for_every_slice(
    use_fake: UseFake, caplog: pytest.LogCaptureFixture
) -> None:
    use_fake(many_repos())

    with caplog.at_level("INFO", logger="features.discovery.services"):
        scan = deep()

    progress = [r.getMessage() for r in caplog.records if "lát" in r.getMessage()]
    assert len(progress) == scan.slices.count()
    assert all(f"Lần quét #{scan.pk}" in line for line in progress)
