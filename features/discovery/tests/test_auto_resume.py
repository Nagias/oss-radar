"""Tự chạy tiếp lần quét bị gián đoạn (trả D-006): chỉ khi gián đoạn, trong 24 giờ, tối đa 3 lần."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest
import respx
from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

from features.discovery import services
from features.discovery.models import ScanRun
from features.discovery.tests.conftest import DEFAULT_REQUEST
from tests.fakes import FakeGitHubSearch, make_search_items

pytestmark = pytest.mark.django_db

UseFake = Callable[[list[dict[str, Any]]], FakeGitHubSearch]

FROM, TO = date(2025, 1, 1), date(2026, 6, 30)


def interrupted_scan(
    *, ago: timedelta = timedelta(minutes=10), origin: str = ScanRun.Origin.MANUAL
) -> ScanRun:
    """Lần quét đã giữ chỗ "đang chạy" rồi app tắt: nhịp sống dừng ở `ago` trước."""
    request = replace(DEFAULT_REQUEST, created_from=FROM, created_to=TO, budget=50, origin=origin)
    scan = services.start_scan(request)
    ScanRun.objects.filter(pk=scan.pk).update(heartbeat_at=timezone.now() - ago)
    services.pause_stale_scans()
    scan.refresh_from_db()
    assert scan.stop_reason == services.REASON_INTERRUPTED
    return scan


def test_resumes_recent_interrupted_manual_scan_and_finishes_it(use_fake: UseFake) -> None:
    use_fake(make_search_items(150, start=FROM, end=TO, stars=lambda i: i))
    scan = interrupted_scan()

    resumed = services.resume_interrupted_scan()

    assert resumed == scan
    scan.refresh_from_db()
    assert scan.status == ScanRun.Status.SUCCEEDED
    assert scan.fetched_count == 150
    assert scan.auto_resume_count == 1
    assert scan.last_auto_resume_at is not None
    assert scan.budget == 50  # tự chạy tiếp không thêm ngân sách


def test_records_the_moment_it_resumed(use_fake: UseFake) -> None:
    use_fake([])
    scan = interrupted_scan()
    moment = timezone.now()

    services.resume_interrupted_scan(now=moment)

    scan.refresh_from_db()
    assert scan.last_auto_resume_at == moment


def test_background_label_names_the_resumed_scan(
    use_fake: UseFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake([])
    scan = interrupted_scan()
    labels: list[str] = []
    monkeypatch.setattr("core.background.relabel", labels.append)

    services.resume_interrupted_scan()

    assert labels == [f"Lần quét #{scan.pk} (tự chạy tiếp)"]


def test_resumes_newest_interrupted_scan_first(use_fake: UseFake) -> None:
    use_fake([])
    older = interrupted_scan()
    newer = interrupted_scan()

    assert services.resume_interrupted_scan() == newer

    older.refresh_from_db()
    assert older.status == ScanRun.Status.PAUSED
    assert older.auto_resume_count == 0


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (ScanRun.Status.PAUSED, services.REASON_STOPPED),
        (ScanRun.Status.PAUSED, services.REASON_CTRL_C),
        (ScanRun.Status.SUCCEEDED_PARTIAL, services.REASON_BUDGET),
        (ScanRun.Status.PAUSED, services.REASON_BUSY),
    ],
)
def test_does_not_resume_user_stopped_ctrl_c_or_budget_paused(
    github_search: respx.Route, status: str, reason: str
) -> None:
    scan = interrupted_scan()
    ScanRun.objects.filter(pk=scan.pk).update(status=status, stop_reason=reason)

    assert services.resume_interrupted_scan() is None

    scan.refresh_from_db()
    assert (scan.status, scan.auto_resume_count) == (status, 0)
    assert github_search.call_count == 0


def test_does_not_resume_scan_user_stopped_before_app_closed(github_search: respx.Route) -> None:
    # Bấm Dừng rồi tắt app trước khi luồng quét kịp thấy cờ: lần quét kẹt "đang chạy" với cờ Dừng.
    scan = services.start_scan(DEFAULT_REQUEST)
    services.request_stop(scan)
    ScanRun.objects.filter(pk=scan.pk).update(heartbeat_at=timezone.now() - timedelta(minutes=10))

    assert services.resume_interrupted_scan() is None

    scan.refresh_from_db()
    assert (scan.status, scan.stop_reason) == (ScanRun.Status.PAUSED, services.REASON_STOPPED)
    assert scan.auto_resume_count == 0
    assert github_search.call_count == 0


def test_does_not_resume_interrupted_scan_user_then_stopped(github_search: respx.Route) -> None:
    scan = interrupted_scan()
    services.request_stop(scan)  # bấm Dừng từ một trang cũ, sau khi lần quét đã bị coi là gián đoạn

    assert services.resume_interrupted_scan() is None

    scan.refresh_from_db()
    assert (scan.status, scan.auto_resume_count) == (ScanRun.Status.PAUSED, 0)
    assert github_search.call_count == 0


def test_gives_way_when_another_scan_starts_meanwhile(
    github_search: respx.Route, monkeypatch: pytest.MonkeyPatch
) -> None:
    scan = interrupted_scan()
    services.start_scan(DEFAULT_REQUEST)  # vd lệnh `scan` ở cửa sổ khác, ngay sau lần kiểm đầu tiên
    real_live_scan = services.live_scan
    checks: list[int] = []

    def live_scan_missed_at_first_check() -> ScanRun | None:
        checks.append(1)
        return None if len(checks) == 1 else real_live_scan()

    monkeypatch.setattr(services, "live_scan", live_scan_missed_at_first_check)

    assert services.resume_interrupted_scan() is None

    scan.refresh_from_db()
    assert (scan.status, scan.stop_reason) == (ScanRun.Status.PAUSED, services.REASON_INTERRUPTED)
    assert scan.auto_resume_count == 0
    assert github_search.call_count == 0


def test_resume_is_counted_before_running_so_a_crashing_scan_cannot_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan = interrupted_scan()

    def crash(scan_id: int) -> None:
        raise RuntimeError("lần quét làm sập luồng nền (giả lập)")

    monkeypatch.setattr(services, "execute_scan", crash)

    with pytest.raises(RuntimeError, match="giả lập"):
        services.resume_interrupted_scan()

    scan.refresh_from_db()
    assert scan.auto_resume_count == 1
    assert scan.last_auto_resume_at is not None


def test_does_not_resume_after_24_hours(github_search: respx.Route) -> None:
    scan = interrupted_scan(ago=timedelta(hours=2))

    assert services.resume_interrupted_scan(now=timezone.now() + timedelta(hours=23)) is None

    scan.refresh_from_db()
    assert scan.status == ScanRun.Status.PAUSED
    assert github_search.call_count == 0


def test_does_not_resume_more_than_three_times(github_search: respx.Route) -> None:
    scan = interrupted_scan()
    ScanRun.objects.filter(pk=scan.pk).update(auto_resume_count=services.MAX_AUTO_RESUMES)

    assert services.resume_interrupted_scan() is None

    scan.refresh_from_db()
    assert scan.status == ScanRun.Status.PAUSED
    assert github_search.call_count == 0


def test_does_not_resume_daily_origin_scan(github_search: respx.Route) -> None:
    scan = interrupted_scan(origin=ScanRun.Origin.DAILY)

    assert services.resume_interrupted_scan() is None

    scan.refresh_from_db()
    assert scan.status == ScanRun.Status.PAUSED
    assert github_search.call_count == 0


def test_waits_while_another_scan_is_live(github_search: respx.Route) -> None:
    scan = interrupted_scan()
    services.start_scan(DEFAULT_REQUEST)

    assert services.resume_interrupted_scan() is None

    scan.refresh_from_db()
    assert (scan.status, scan.auto_resume_count) == (ScanRun.Status.PAUSED, 0)
    assert github_search.call_count == 0


def test_auto_resume_is_a_scheduled_job() -> None:
    jobs = [import_string(path) for path in settings.SCHEDULED_JOBS]

    assert services.resume_interrupted_scan in jobs


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github
