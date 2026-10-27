"""Đọc báo cáo rising star từ dữ liệu đã lưu: lọc theo ngưỡng, "mới vào", lý do, chưa xác minh."""

from datetime import UTC, datetime, time, timedelta

import pytest

from features.rising import services
from features.rising.growth import FLAG_LABELS, Flag, sparkline_points
from features.rising.models import DailyRun, RisingCheck
from features.rising.tests.conftest import DAY, make_check, make_repo, make_run
from features.scoring.rules import SuspicionLevel
from tests.factories import label_repository

pytestmark = pytest.mark.django_db

Status = DailyRun.Status
Step = DailyRun.Step
Source = RisingCheck.Source


def test_daily_report_filters_by_thresholds() -> None:
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

    wider = services.daily_report(run, max_stars=2000, min_gain=40, sort="gain")

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

    assert [row.check for row in report.unverified] == [age_row, snapshot_row]
    assert report.unverified[1].check.baseline_day == DAY - timedelta(days=3)
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


def test_report_counts_every_verified_row_whatever_the_thresholds() -> None:
    run = make_run()
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)
    make_check(run, 2, stars=200, gain_7d=10)  # đã xác minh nhưng chưa đạt ngưỡng
    make_check(run, 3, stars=100, gain_7d=80, source=Source.SNAPSHOT)  # chưa xác minh

    report = services.daily_report(run)

    assert report.verified_count == 2
    assert len(report.rising) == 1


# --- Điểm, sắp xếp, ẩn repo nghi star giả (F-006) ----------------------------------------------


def suspicious_repo(github_id: int) -> None:
    """Repo "Nghi cao": 2 fork trên 613 star, không commit nào sau ngày tạo (45 + 20 = 65)."""
    created = DAY - timedelta(days=30)
    make_repo(
        github_id,
        created=created,
        stars=613,
        forks=2,
        pushed_at=datetime.combine(created, time(18), tzinfo=UTC),
    )


def review_repo(github_id: int) -> None:
    """Repo "Cần xem": 4 fork trên 1.000 star (45), có commit sau ngày tạo."""
    make_repo(github_id, stars=1000, forks=4)


def test_default_order_is_potential_and_gain_order_on_request() -> None:
    run = make_run()
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)  # 22 + 12 + 20 + 20 = 74
    make_check(run, 2, stars=999, gain_7d=50, is_rising=True)  # 14 + 0 + 20 + 20 = 54
    make_check(run, 3, stars=1000, gain_7d=200)  # 26 + 6 + 10 + 20 = 62
    make_check(run, 4, stars=200, gain_7d=49)  # 14 + 12 + 20 + 20 = 66

    by_potential = services.daily_report(run, max_stars=2000, min_gain=40)
    by_gain = services.daily_report(run, max_stars=2000, min_gain=40, sort="gain")

    assert [row.repository.github_id for row in by_potential.rising] == [1, 4, 3, 2]
    totals = [row.scores.potential.total for row in by_potential.rising if row.scores.potential]
    assert totals == [74, 66, 62, 54]
    assert [row.repository.github_id for row in by_gain.rising] == [3, 1, 2, 4]


def test_rows_carry_quality_potential_and_suspicion() -> None:
    run = make_run()
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)

    [row] = services.daily_report(run).rising

    assert row.scores.quality.total > 0
    assert row.scores.potential is not None
    assert row.scores.potential.estimated is False
    assert row.scores.suspicion.level == SuspicionLevel.CLEAR


def test_high_suspicion_rows_are_hidden_after_filters_review_rows_stay() -> None:
    run = make_run()
    suspicious_repo(1)
    make_check(run, 1, stars=613, gain_7d=300, is_rising=True)
    review_repo(2)
    make_check(run, 2, stars=900, gain_7d=60, is_rising=True)
    make_check(run, 3, stars=300, gain_7d=100, is_rising=True)
    suspicious_repo(4)
    make_check(run, 4, stars=613, gain_7d=10)  # không qua bộ lọc mặc định

    report = services.daily_report(run)
    wide = services.daily_report(run, min_gain=0)

    assert [row.repository.github_id for row in report.rising] == [3, 2]
    assert [row.repository.github_id for row in report.hidden] == [1]
    assert report.rising[1].scores.suspicion.level == SuspicionLevel.REVIEW
    assert report.hidden[0].scores.suspicion.points == 65
    assert report.hidden_rising_count == 1
    assert [row.repository.github_id for row in wide.hidden] == [1, 4]
    assert wide.hidden_rising_count == 1  # đếm trong rising star của lượt, không theo bộ lọc


def test_unverified_rows_carry_estimated_potential() -> None:
    run = make_run()
    make_check(run, 1, stars=300, gain_7d=30, source=Source.SNAPSHOT)

    [row] = services.daily_report(run).unverified

    assert row.check.repository.github_id == 1
    assert row.potential.estimated is True
    assert row.potential.total == 36  # tốc độ 10 + tăng tương đối 6 + còn chỗ lớn 20 + đà bền 0


# --- Nhãn nhóm và lọc theo nhóm (F-010) ------------------------------------------------------


def three_labelled_risers() -> DailyRun:
    run = make_run()
    for github_id in (1, 2, 3):
        make_check(run, github_id, stars=300, gain_7d=100 + github_id, is_rising=True)
    label_repository(make_repo(1), audience=("creator",), aspects=("video",))
    label_repository(make_repo(2), audience=("marketer",), aspects=("ads",))
    return run


def ids(rows: list[services.RisingRow]) -> list[int]:
    return sorted(row.repository.github_id for row in rows)


def test_rows_carry_labels() -> None:
    run = three_labelled_risers()

    rows = {row.repository.github_id: row for row in services.daily_report(run).rising}

    assert rows[1].labels is not None
    assert [c.code for c in rows[1].labels.aspects] == ["video"]
    assert rows[3].labels is None  # chưa phân loại


def test_group_filters_or_within_axis_and_between_axes() -> None:
    run = three_labelled_risers()

    assert ids(services.daily_report(run, audience=("creator",)).rising) == [1]
    assert ids(services.daily_report(run, audience=("creator", "marketer")).rising) == [1, 2]
    assert ids(services.daily_report(run, audience=("creator",), aspects=("ads",)).rising) == []
    assert ids(services.daily_report(run, aspects=("ads",)).rising) == [2]


# --- Chia trang: trang mặc định nhẹ dù lượt có hàng trăm dòng ---------------------------------


def test_rising_table_is_paged_and_page_is_clamped() -> None:
    run = make_run()
    for github_id in range(1, services.RISING_PAGE_SIZE + 3):
        make_check(run, github_id, stars=300, gain_7d=100 + github_id, is_rising=True)
    total = services.RISING_PAGE_SIZE + 2

    first = services.daily_report(run, sort="gain")
    second = services.daily_report(run, sort="gain", page=2)
    beyond = services.daily_report(run, sort="gain", page=99)
    below = services.daily_report(run, sort="gain", page=0)

    assert len(first.rising) == services.RISING_PAGE_SIZE
    assert (first.rising_page.total, first.rising_page.page, first.rising_page.pages) == (
        total,
        1,
        2,
    )
    # Tăng ít nhất nằm cuối, ở trang 2 (giữ đúng thứ tự, không sắp lại).
    assert [row.repository.github_id for row in second.rising] == [2, 1]
    assert second.rising_page.first_index == services.RISING_PAGE_SIZE + 1
    assert beyond.rising_page.page == 2
    assert below.rising_page.page == 1


def test_unverified_section_is_paged_apart_from_rising_table() -> None:
    run = make_run()
    make_check(run, 1, stars=300, gain_7d=100, is_rising=True)
    for github_id in range(2, services.UNVERIFIED_PAGE_SIZE + 4):
        make_check(run, github_id, stars=300, gain_7d=github_id, source=Source.SNAPSHOT)
    total = services.UNVERIFIED_PAGE_SIZE + 2

    first = services.daily_report(run)
    second = services.daily_report(run, page=5, unverified_page=2)

    assert len(first.unverified) == services.UNVERIFIED_PAGE_SIZE
    assert (first.unverified_page.total, first.unverified_page.pages) == (total, 2)
    assert [row.check.repository.github_id for row in second.unverified] == [3, 2]
    assert ids(second.rising) == [1]  # trang rising quá cuối → trang cuối, không ảnh hưởng mục kia
    assert second.rising_page.page == 1


def test_hidden_rows_are_not_counted_in_rising_pages() -> None:
    run = make_run()
    suspicious_repo(1)
    make_check(run, 1, stars=613, gain_7d=300, is_rising=True)
    make_check(run, 2, stars=300, gain_7d=100, is_rising=True)

    report = services.daily_report(run)

    assert report.rising_page.total == 1
    assert [row.repository.github_id for row in report.hidden] == [1]
