"""Tính star tăng từ lịch sử chính thức hoặc ảnh chụp: toàn hàm thuần, số mong đợi tính tay.

Lịch sử star dùng phản hồi THẬT của GitHub (tests/fixtures/github/) và đi qua đúng bộ phân tích của
client, không dựng tay.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from itertools import chain

import pytest
import respx
from pytest_django.fixtures import Settings

from features.catalog.services import StarPoint
from features.rising.growth import (
    FLAG_LABELS,
    Flag,
    estimate_gain_7d,
    growth_from_history,
    growth_percent_7d,
    is_rising,
    last_complete_utc_day,
    sparkline_points,
    warning_flags,
)
from integrations.github.client import GitHubClient, get_github_client
from integrations.github.schemas import StarHistory
from tests.factories import load_fixture_list
from tests.fakes import FakeTime

VIETNAM = timezone(timedelta(hours=7))
TODAY = date(2026, 10, 22)


@pytest.fixture
def github(settings: Settings, fake_time: FakeTime) -> Iterator[GitHubClient]:
    settings.GITHUB_TOKEN = "test-token"
    with get_github_client(sleep=fake_time.sleep) as client:
        yield client


def _fetch_history(
    github: GitHubClient, http_mock: respx.MockRouter, settings: Settings, *, fixture: str
) -> StarHistory:
    github_id = 42976210
    url = f"{settings.GITHUB_API_URL}/repositories/{github_id}/stargazers/history"
    http_mock.get(url).respond(json=load_fixture_list(f"github/{fixture}"))
    return github.star_history(github_id)


@pytest.fixture
def old_history(
    github: GitHubClient, http_mock: respx.MockRouter, settings: Settings
) -> StarHistory:
    """Repo lâu năm: 6 tuần đầy đủ, từ Chủ nhật 13/09 tới tuần chứa 22/10/2026."""
    return _fetch_history(github, http_mock, settings, fixture="star_history_old.json")


@pytest.fixture
def young_history(
    github: GitHubClient, http_mock: respx.MockRouter, settings: Settings
) -> StarHistory:
    """Repo mới tạo: GitHub chỉ trả 2 tuần (11/10 và 18/10) dù xin 6."""
    return _fetch_history(github, http_mock, settings, fixture="star_history_recent.json")


# --- Ngày UTC đã trọn --------------------------------------------------------------------------


def test_last_complete_utc_day_at_7am_vietnam_is_yesterday_utc() -> None:
    # 07:00 giờ VN = 00:00 UTC ngày 22 → ngày UTC đã trọn gần nhất là 21.
    now = datetime(2026, 10, 22, 7, 0, tzinfo=VIETNAM)

    assert last_complete_utc_day(now) == date(2026, 10, 21)


def test_last_complete_utc_day_before_7am_vietnam_is_two_days_back() -> None:
    # 06:30 giờ VN = 23:30 UTC ngày 21 → ngày 21 chưa hết, nên ngày trọn gần nhất là 20.
    now = datetime(2026, 10, 22, 6, 30, tzinfo=VIETNAM)

    assert last_complete_utc_day(now) == date(2026, 10, 20)


def test_last_complete_utc_day_accepts_utc_and_far_west_timezones() -> None:
    assert last_complete_utc_day(datetime(2026, 10, 22, 0, 0, tzinfo=UTC)) == date(2026, 10, 21)
    # 20:00 ở UTC-5 = 01:00 UTC ngày 23 → ngày trọn gần nhất là 22.
    west = timezone(timedelta(hours=-5))
    assert last_complete_utc_day(datetime(2026, 10, 22, 20, 0, tzinfo=west)) == date(2026, 10, 22)


def test_last_complete_utc_day_rejects_naive_datetime() -> None:
    # Giờ không múi giờ sẽ bị hiểu theo múi giờ máy → tính sai ngày mà không báo lỗi.
    with pytest.raises(ValueError, match="múi giờ"):
        last_complete_utc_day(datetime(2026, 10, 22, 7, 0))  # noqa: DTZ001


# --- Tăng 1/7/30 ngày từ lịch sử chính thức ----------------------------------------------------


def test_growth_from_real_fixture_sums_complete_days_only(old_history: StarHistory) -> None:
    # Cửa sổ 30 ngày kết thúc 21/10 → bắt đầu 22/09. Ngày 22/10 (đang dở, 2 star) bị bỏ.
    growth = growth_from_history(old_history, window_end=date(2026, 10, 21))

    assert growth.window_end == date(2026, 10, 21)
    expected_by_week = (
        (3, 6, 7, 3, 3),  # 22/09 - 26/09 (cuối tuần 20/09)
        (2, 5, 2, 6, 2, 5, 1),  # tuần 27/09
        (1, 4, 4, 4, 4, 6, 7),  # tuần 04/10
        (6, 5, 3, 9, 9, 3, 3),  # tuần 11/10
        (7, 6, 4, 7),  # 18/10 - 21/10 (đầu tuần 18/10)
    )
    assert growth.series == tuple(chain.from_iterable(expected_by_week))
    assert growth.gain_1d == 7  # 21/10
    assert growth.gain_7d == 39  # 15/10..21/10 = 9+3+3+7+6+4+7
    assert growth.gain_30d == 137  # 22+23+30+38+24


def test_growth_spanning_week_boundary_and_sunday_window_end(old_history: StarHistory) -> None:
    # window_end là Chủ nhật 18/10: ngày cuối là ngày ĐẦU của tuần mới nhất; 19-22/10 bị bỏ.
    # Ngày đầu cửa sổ là 19/09 (thứ Bảy, ngày CUỐI của tuần 13/09).
    growth = growth_from_history(old_history, window_end=date(2026, 10, 18))

    assert len(growth.series) == 30
    assert growth.series[0] == 4  # 19/09
    assert growth.series[1:8] == (3, 1, 3, 6, 7, 3, 3)  # tuần 20/09 nằm trọn trong cửa sổ
    assert growth.series[-1] == 7  # 18/10
    assert growth.gain_1d == 7
    assert growth.gain_7d == 39  # 12/10..18/10 = 5+3+9+9+3+3+7
    assert growth.gain_30d == 128  # 4+26+23+30+38+7


def test_growth_with_saturday_window_end_closes_on_last_day_of_week(
    old_history: StarHistory,
) -> None:
    growth = growth_from_history(old_history, window_end=date(2026, 10, 17))

    assert growth.gain_1d == 3  # thứ Bảy 17/10
    assert growth.gain_7d == 38  # trọn tuần 11/10 = 6+5+3+9+9+3+3


def test_growth_treats_missing_days_as_zero(young_history: StarHistory) -> None:
    # Repo mới: lịch sử chỉ từ 11/10 → 19 ngày đầu của cửa sổ (22/09..10/10) không có dữ liệu = 0.
    growth = growth_from_history(young_history, window_end=date(2026, 10, 21))

    assert growth.series == (0,) * 19 + (0, 0, 0, 690, 139, 49, 36, 4, 8, 6, 6)
    assert growth.gain_1d == 6
    assert growth.gain_7d == 248  # 139+49+36+4+8+6+6
    assert growth.gain_30d == 938  # 690 + 248


def test_growth_from_empty_history_is_all_zero() -> None:
    growth = growth_from_history(StarHistory(weeks=()), window_end=date(2026, 10, 21))

    assert growth.series == (0,) * 30
    assert (growth.gain_1d, growth.gain_7d, growth.gain_30d) == (0, 0, 0)


# --- Phần trăm tăng ---------------------------------------------------------------------------


def test_growth_percent_is_gain_over_stars_seven_days_ago() -> None:
    assert growth_percent_7d(150, 50) == pytest.approx(50.0)  # 7 ngày trước có 100
    assert growth_percent_7d(1000, 250) == pytest.approx(33.3333, abs=1e-3)  # 250/750
    assert growth_percent_7d(100, 0) == pytest.approx(0.0)


def test_growth_percent_handles_zero_base() -> None:
    # Mọi star đều mới trong 7 ngày (hoặc nhiều hơn tổng hiện có): không có mốc để chia.
    assert growth_percent_7d(50, 50) is None
    assert growth_percent_7d(30, 50) is None


# --- Ước lượng từ ảnh chụp --------------------------------------------------------------------


def test_estimate_from_baseline_scales_to_seven_days() -> None:
    two_days_ago = StarPoint(day=TODAY - timedelta(days=2), stars=80)

    estimate = estimate_gain_7d(
        stars_now=100, baseline=two_days_ago, today=TODAY, created_on=date(2025, 1, 1)
    )

    assert estimate == 70  # +20 trong 2 ngày → 20 * 7 / 2


def test_estimate_from_baseline_rounds_and_scales_down_old_baseline() -> None:
    created_on = date(2025, 1, 1)
    three_days_ago = StarPoint(day=TODAY - timedelta(days=3), stars=90)
    two_weeks_ago = StarPoint(day=TODAY - timedelta(days=14), stars=86)

    # 10 * 7 / 3 = 23,33 → 23
    assert (
        estimate_gain_7d(stars_now=100, baseline=three_days_ago, today=TODAY, created_on=created_on)
        == 23
    )
    # +14 trong 14 ngày → 7 (mốc cũ hơn 7 ngày thì quy xuống)
    assert (
        estimate_gain_7d(stars_now=100, baseline=two_weeks_ago, today=TODAY, created_on=created_on)
        == 7
    )


def test_estimate_from_baseline_wins_over_age_of_young_repo() -> None:
    created_on = TODAY - timedelta(days=10)
    baseline = StarPoint(day=TODAY - timedelta(days=7), stars=90)

    assert (
        estimate_gain_7d(stars_now=100, baseline=baseline, today=TODAY, created_on=created_on) == 10
    )


def test_estimate_rejects_baseline_not_before_today() -> None:
    # Mốc phải là ngày trước hôm nay (baseline_snapshots đảm bảo); cùng ngày sẽ chia cho 0.
    baseline = StarPoint(day=TODAY, stars=90)

    with pytest.raises(ValueError, match="trước hôm nay"):
        estimate_gain_7d(stars_now=100, baseline=baseline, today=TODAY, created_on=date(2025, 1, 1))


def test_estimate_young_repo_without_baseline() -> None:
    # Dưới 7 ngày tuổi: lấy nguyên số star (chưa đủ một tuần để quy đổi).
    assert (
        estimate_gain_7d(
            stars_now=40, baseline=None, today=TODAY, created_on=TODAY - timedelta(days=3)
        )
        == 40
    )
    # Từ 7 ngày: star / tuổi * 7. Tuổi 14, 100 star → 50.
    assert (
        estimate_gain_7d(
            stars_now=100, baseline=None, today=TODAY, created_on=TODAY - timedelta(days=14)
        )
        == 50
    )
    # Đúng 7 ngày tuổi thì đã quy đổi (7/7 = nguyên số star).
    assert (
        estimate_gain_7d(
            stars_now=100, baseline=None, today=TODAY, created_on=TODAY - timedelta(days=7)
        )
        == 100
    )


def test_estimate_young_repo_created_today_does_not_divide_by_zero() -> None:
    assert estimate_gain_7d(stars_now=12, baseline=None, today=TODAY, created_on=TODAY) == 12


def test_estimate_young_repo_age_limit_is_thirty_days_inclusive() -> None:
    thirty_days_old = TODAY - timedelta(days=30)
    thirty_one_days_old = TODAY - timedelta(days=31)

    # 100 * 7 / 30 = 23,33 → 23
    assert (
        estimate_gain_7d(stars_now=100, baseline=None, today=TODAY, created_on=thirty_days_old)
        == 23
    )
    assert (
        estimate_gain_7d(stars_now=100, baseline=None, today=TODAY, created_on=thirty_one_days_old)
        is None
    )


def test_estimate_old_repo_without_baseline_is_none() -> None:
    assert (
        estimate_gain_7d(stars_now=500, baseline=None, today=TODAY, created_on=date(2024, 3, 1))
        is None
    )


# --- Quy tắc rising star ----------------------------------------------------------------------


def test_is_rising_boundaries() -> None:
    assert is_rising(999, 50) is True  # dưới 1.000 star, tăng đúng 50
    assert is_rising(1000, 80) is False  # đủ 1.000 star thì không còn là "sao đang lên"
    assert is_rising(500, 49) is False  # tăng chưa tới 50
    assert is_rising(500, 50) is True


def test_is_rising_thresholds_can_be_overridden() -> None:
    assert is_rising(1500, 80, max_stars=2000, min_gain=80) is True
    assert is_rising(1500, 79, max_stars=2000, min_gain=80) is False
    assert is_rising(2000, 80, max_stars=2000, min_gain=80) is False


# --- Cờ cảnh giác -----------------------------------------------------------------------------


def _week_after_idle(last_seven: tuple[int, ...]) -> tuple[int, ...]:
    """Chuỗi 30 ngày: 23 ngày im ắng rồi 7 ngày cuối cho trước."""
    return (0,) * 23 + last_seven


def test_warning_flags_burst_at_seventy_percent_in_one_day() -> None:
    seventy = _week_after_idle((70, 5, 5, 5, 5, 5, 5))  # tổng 100, ngày cao nhất 70 = 70%
    sixty_nine = _week_after_idle((69, 5, 5, 5, 5, 5, 6))  # tổng 100, ngày cao nhất 69%

    assert warning_flags(series=seventy, age_days=400, description="Có mô tả") == (Flag.BURST,)
    assert warning_flags(series=sixty_nine, age_days=400, description="Có mô tả") == ()


def test_warning_flags_burst_only_looks_at_last_seven_days() -> None:
    # Ngày đột biến 700 nằm ở vị trí -8: ngoài cửa sổ 7 ngày nên không tính.
    series = (0,) * 22 + (700,) + (10,) * 7

    assert warning_flags(series=series, age_days=400, description="Có mô tả") == ()


def test_warning_flags_no_burst_without_any_gain() -> None:
    assert warning_flags(series=(0,) * 30, age_days=400, description="Có mô tả") == ()


def test_warning_flags_burst_with_flat_week_is_not_flagged() -> None:
    # 7 ngày đều 10 star: mỗi ngày chiếm 1/7 ≈ 14%.
    assert warning_flags(series=(10,) * 30, age_days=400, description="Có mô tả") == ()


def test_warning_flags_very_new_below_seven_days() -> None:
    steady = (10,) * 30

    assert warning_flags(series=steady, age_days=6, description="Có mô tả") == (Flag.VERY_NEW,)
    assert warning_flags(series=steady, age_days=7, description="Có mô tả") == ()


def test_warning_flags_missing_description() -> None:
    steady = (10,) * 30

    assert warning_flags(series=steady, age_days=400, description="") == (Flag.NO_DESCRIPTION,)
    assert warning_flags(series=steady, age_days=400, description="  \n ") == (Flag.NO_DESCRIPTION,)


def test_warning_flags_keep_a_stable_order_when_all_apply() -> None:
    series = _week_after_idle((90, 1, 1, 1, 1, 1, 5))

    assert warning_flags(series=series, age_days=2, description="") == (
        Flag.BURST,
        Flag.VERY_NEW,
        Flag.NO_DESCRIPTION,
    )


def test_every_flag_has_a_vietnamese_label() -> None:
    assert FLAG_LABELS == {
        Flag.BURST: "Dồn một ngày — nên mở xem",
        Flag.VERY_NEW: "Repo rất mới (dưới 7 ngày)",
        Flag.NO_DESCRIPTION: "Không có mô tả",
    }
    assert {flag.value for flag in Flag} == {"burst", "very_new", "no_description"}


# --- Biểu đồ nhỏ ------------------------------------------------------------------------------


def test_sparkline_points_scale_to_box_with_zero_at_bottom() -> None:
    # Trục y của SVG đi xuống: 0 star ở đáy (y = cao), giá trị lớn nhất ở đỉnh (y = 0).
    points = sparkline_points((0, 5, 10), width=100, height=20)

    assert points == "0.0,20.0 50.0,10.0 100.0,0.0"


def test_sparkline_points_count_and_flat_series() -> None:
    flat = sparkline_points((0,) * 30)
    pairs = flat.split(" ")

    assert len(pairs) == 30
    assert pairs[0] == "0.0,24.0"  # mặc định rộng 120, cao 24
    assert pairs[-1] == "120.0,24.0"
    assert {pair.split(",")[1] for pair in pairs} == {"24.0"}  # toàn 0 → đường nằm ở đáy


def test_sparkline_points_x_is_evenly_spaced() -> None:
    xs = [float(pair.split(",")[0]) for pair in sparkline_points((1, 2, 3, 4, 5), width=80).split()]

    assert xs == [0.0, 20.0, 40.0, 60.0, 80.0]


def test_sparkline_points_of_single_value_and_empty_series() -> None:
    assert sparkline_points((7,), width=100, height=20) == "0.0,0.0"
    assert sparkline_points((), width=100, height=20) == ""
