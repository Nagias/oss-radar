"""Đọc báo cáo rising star từ dữ liệu đã lưu: lọc theo ngưỡng, "mới vào", lý do, chưa xác minh."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from django.utils import timezone

from features.catalog.models import Repository
from features.catalog.services import upsert_repositories
from features.rising import services
from features.rising.growth import FLAG_LABELS, Flag, sparkline_points
from features.rising.models import DailyRun, RisingCheck
from tests.factories import make_github_repo

pytestmark = pytest.mark.django_db

Status = DailyRun.Status
Step = DailyRun.Step
Source = RisingCheck.Source

DAY = date(2026, 10, 22)
WINDOW_END = date(2026, 10, 21)


def make_run(
    day: date = DAY, *, status: str = Status.SUCCEEDED, step: int = Step.REPORT
) -> DailyRun:
    return DailyRun.objects.create(day=day, status=status, step=step, window_end=WINDOW_END)


def make_repo(
    github_id: int, *, created: date = date(2025, 1, 1), description: str = "Một repo giả lập"
) -> Repository:
    [outcome] = upsert_repositories(
        [
            make_github_repo(
                github_id=github_id,
                full_name=f"gia-lap/repo-{github_id}",
                description=description,
                created_at=datetime.combine(created, time(12), tzinfo=UTC),
            )
        ],
        seen_at=timezone.now(),
    )
    return outcome.repository


def make_check(
    run: DailyRun,
    github_id: int,
    *,
    stars: int,
    gain_7d: int,
    source: str = Source.HISTORY,
    is_rising: bool = False,
    flags: list[str] | None = None,
) -> RisingCheck:
    repository = Repository.objects.filter(github_id=github_id).first() or make_repo(github_id)
    return RisingCheck.objects.create(
        daily_run=run,
        repository=repository,
        stars=stars,
        source=source,
        gain_1d=gain_7d // 7 if source == Source.HISTORY else None,
        gain_7d=gain_7d,
        gain_30d=gain_7d * 3 if source == Source.HISTORY else None,
        series=[gain_7d // 7] * 30 if source == Source.HISTORY else [],
        window_end=WINDOW_END if source == Source.HISTORY else None,
        baseline_day=DAY - timedelta(days=3) if source == Source.SNAPSHOT else None,
        is_rising=is_rising,
        flags=flags or [],
    )


def test_daily_report_filters_by_thresholds_and_sorts_by_gain() -> None:
    run = make_run()
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)
    make_check(run, 2, stars=999, gain_7d=50, is_rising=True)
    make_check(run, 3, stars=1000, gain_7d=200)  # không dưới 1.000 star
    make_check(run, 4, stars=200, gain_7d=49)  # tăng chưa tới 50
    make_check(run, 5, stars=100, gain_7d=300, source=Source.SNAPSHOT)  # chưa xác minh

    report = services.daily_report(run)

    assert report.run == run
    assert [row.repository.github_id for row in report.rising] == [1, 2]
    assert [row.check.gain_7d for row in report.rising] == [120, 50]

    wider = services.daily_report(run, max_stars=2000, min_gain=40)

    assert [row.repository.github_id for row in wider.rising] == [3, 1, 2, 4]


def test_rising_row_has_percent_age_flags_and_sparkline() -> None:
    run = make_run()
    make_repo(7, created=DAY - timedelta(days=5), description="")
    check = make_check(
        run, 7, stars=340, gain_7d=120, is_rising=True, flags=["burst", "no_description"]
    )

    [row] = services.daily_report(run).rising

    assert row.check == check
    assert row.growth_percent == pytest.approx(120 * 100 / 220)
    assert row.age_days == 5  # tuổi tính tới ngày của lượt, khớp với cờ "Repo rất mới"
    assert row.flag_labels == (FLAG_LABELS[Flag.BURST], FLAG_LABELS[Flag.NO_DESCRIPTION])
    assert row.sparkline == sparkline_points([17] * 30)


def test_new_entry_compares_with_previous_run() -> None:
    oldest = make_run(DAY - timedelta(days=3))
    make_check(oldest, 1, stars=300, gain_7d=90, is_rising=True)
    previous = make_run(DAY - timedelta(days=2), status=Status.SUCCEEDED_PARTIAL)
    make_check(previous, 2, stars=300, gain_7d=90, is_rising=True)
    make_check(previous, 3, stars=300, gain_7d=10)  # có xét nhưng không phải rising
    # Hôm qua: lượt bị đóng khi đang xác minh (chưa qua bước báo cáo) → không tính là báo cáo trước.
    unreported = make_run(
        DAY - timedelta(days=1), status=Status.SUCCEEDED_PARTIAL, step=Step.VERIFY
    )
    make_check(unreported, 4, stars=300, gain_7d=90, is_rising=True)
    run = make_run()
    for github_id in (1, 2, 3, 4):
        make_check(run, github_id, stars=300, gain_7d=100 + github_id, is_rising=True)

    report = services.daily_report(run)

    new = {row.repository.github_id: row.is_new_entry for row in report.rising}
    assert new == {1: True, 2: False, 3: True, 4: True}
    assert [row.is_new_entry for row in services.daily_report(oldest).rising] == [True]


def test_reason_text_has_threshold_and_utc_window() -> None:
    run = make_run()
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)

    [row] = services.daily_report(run).rising

    assert row.reason == (
        "+120 star trong 7 ngày (ngưỡng 50) · đang 340 star (dưới 1.000) · "
        "nguồn: lịch sử star GitHub, ngày UTC 15/10–21/10"  # noqa: RUF001 — đúng mẫu thiết kế
    )

    [custom] = services.daily_report(run, max_stars=500, min_gain=100).rising

    assert "(ngưỡng 100)" in custom.reason
    assert "(dưới 500)" in custom.reason


def test_unverified_section_lists_snapshot_and_age_rows() -> None:
    run = make_run()
    snapshot_row = make_check(run, 1, stars=300, gain_7d=30, source=Source.SNAPSHOT)
    age_row = make_check(run, 2, stars=80, gain_7d=80, source=Source.AGE)
    make_check(run, 3, stars=300, gain_7d=100, is_rising=True)
    other_run = make_run(DAY - timedelta(days=1))
    make_check(other_run, 4, stars=300, gain_7d=500, source=Source.AGE)

    report = services.daily_report(run)

    assert report.unverified == [age_row, snapshot_row]
    assert report.unverified[1].baseline_day == DAY - timedelta(days=3)
    assert [row.repository.github_id for row in report.rising] == [3]
    assert report.scans == []


def test_latest_report_run_skips_runs_not_reported() -> None:
    today = make_run(DAY, status=Status.RUNNING, step=Step.VERIFY)
    yesterday = make_run(DAY - timedelta(days=1))
    make_run(DAY - timedelta(days=2), status=Status.SUCCEEDED_PARTIAL, step=Step.RESCAN)
    make_run(DAY - timedelta(days=3), status=Status.FAILED)
    partial = make_run(DAY - timedelta(days=4), status=Status.SUCCEEDED_PARTIAL)

    assert services.latest_report_run() == yesterday
    assert services.report_days() == [yesterday.day, partial.day]
    assert services.report_run_for(yesterday.day) == yesterday
    assert services.report_run_for(DAY - timedelta(days=2)) is None
    assert services.report_run_for(today.day) is None


def test_no_report_before_first_run() -> None:
    assert services.latest_report_run() is None
    assert services.report_days() == []
