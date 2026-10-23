"""Tính star tăng 1/7/30 ngày, ước lượng từ ảnh chụp, quy tắc rising star và cờ cảnh giác.

Toàn hàm thuần: không đọc CSDL, không gọi mạng. Nhờ vậy mọi con số đều kiểm được bằng test tính tay
(nguyên tắc 6: điểm số phải giải thích được từng thành phần).

Ngày của lịch sử star là ngày UTC (GitHub chia ngày theo UTC), khác ngày giờ Việt Nam của ảnh chụp.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from features.catalog.services import StarPoint
from integrations.github.schemas import StarHistory

WINDOW_DAYS = 7
SERIES_DAYS = 30

# Rising star: dưới 1.000 star (nhỏ hơn hẳn) và tăng từ 50 star trở lên trong 7 ngày.
RISING_MAX_STARS = 1000
RISING_MIN_GAIN_7D = 50

# Lọc thô trước khi xác minh: ước lượng từ 25 (một nửa ngưỡng vì ước lượng còn thô) là ứng viên.
CANDIDATE_MIN_ESTIMATE_7D = 25
YOUNG_REPO_DAYS = 30

# Cờ cảnh giác (chỉ gắn nhãn, không loại repo).
BURST_SHARE = 0.7
VERY_NEW_DAYS = 7


@dataclass(frozen=True, slots=True)
class Growth:
    """Star tăng tính từ các ngày UTC đã trọn, kết thúc ở `window_end` (tính cả ngày này).

    `series` có đúng `SERIES_DAYS` số, cũ → mới; số cuối là ngày `window_end`.
    """

    window_end: date
    gain_1d: int
    gain_7d: int
    gain_30d: int
    series: tuple[int, ...]


class Flag(StrEnum):
    BURST = "burst"
    VERY_NEW = "very_new"
    NO_DESCRIPTION = "no_description"


FLAG_LABELS: dict[Flag, str] = {
    Flag.BURST: "Dồn một ngày — nên mở xem",
    Flag.VERY_NEW: "Repo rất mới (dưới 7 ngày)",
    Flag.NO_DESCRIPTION: "Không có mô tả",
}


def last_complete_utc_day(now: datetime) -> date:
    """Ngày UTC gần nhất đã trọn vẹn: ngày UTC của `now` trừ 1 (ngày đang chạy còn dở)."""
    if now.tzinfo is None:
        raise ValueError("`now` phải có múi giờ, nếu không ngày UTC bị tính theo múi giờ máy")
    return now.astimezone(UTC).date() - timedelta(days=1)


def growth_from_history(history: StarHistory, *, window_end: date) -> Growth:
    """Tăng 1/7/30 ngày và chuỗi 30 ngày kết thúc ở `window_end`, từ lịch sử star chính thức.

    Ngày không có trong lịch sử tính là 0 (repo mới chỉ có vài tuần). Ngày sau `window_end`
    (hôm nay đang dở) bị bỏ.
    """
    daily: dict[date, int] = {}
    for week in history.weeks:
        for offset, new_stars in enumerate(week.days):
            daily[week.start + timedelta(days=offset)] = new_stars

    first_day = window_end - timedelta(days=SERIES_DAYS - 1)
    series = tuple(daily.get(first_day + timedelta(days=index), 0) for index in range(SERIES_DAYS))
    return Growth(
        window_end=window_end,
        gain_1d=series[-1],
        gain_7d=sum(series[-WINDOW_DAYS:]),
        gain_30d=sum(series),
        series=series,
    )


def growth_percent_7d(stars_now: int, gain_7d: int) -> float | None:
    """Tăng bao nhiêu phần trăm so với số star cách đây 7 ngày; không có mốc để chia thì None."""
    stars_before = stars_now - gain_7d
    if stars_before <= 0:
        return None
    return gain_7d * 100 / stars_before


def estimate_gain_7d(
    *, stars_now: int, baseline: StarPoint | None, today: date, created_on: date
) -> int | None:
    """Ước lượng star tăng trong 7 ngày khi chưa có lịch sử chính thức. None nếu không đủ cơ sở.

    - Có ảnh chụp cũ: quy chênh lệch so với ảnh chụp đó ra 7 ngày.
    - Không có ảnh chụp mà repo tạo trong `YOUNG_REPO_DAYS` ngày: lấy star hiện có chia theo tuổi
      repo, quy ra 7 ngày (dưới `VERY_NEW_DAYS` ngày tuổi thì lấy nguyên số star).
    - Còn lại (repo cũ, chưa có mốc): chưa đủ dữ liệu.
    """
    if baseline is not None:
        span_days = (today - baseline.day).days
        if span_days <= 0:
            raise ValueError(f"Ảnh chụp mốc phải có ngày trước hôm nay, nhận {baseline.day}")
        return round((stars_now - baseline.stars) * WINDOW_DAYS / span_days)

    age_days = (today - created_on).days
    if age_days > YOUNG_REPO_DAYS:
        return None
    if age_days < VERY_NEW_DAYS:
        return stars_now
    return round(stars_now * WINDOW_DAYS / age_days)


def is_rising(
    stars_now: int,
    gain_7d: int,
    *,
    max_stars: int = RISING_MAX_STARS,
    min_gain: int = RISING_MIN_GAIN_7D,
) -> bool:
    """Rising star: star nhỏ hơn `max_stars` và tăng từ `min_gain` trở lên trong 7 ngày."""
    return stars_now < max_stars and gain_7d >= min_gain


def warning_flags(*, series: Sequence[int], age_days: int, description: str) -> tuple[Flag, ...]:
    """Cờ cảnh giác để người dùng tự cân nhắc; không có cờ nào loại repo."""
    flags: list[Flag] = []
    last_week = series[-WINDOW_DAYS:]
    total = sum(last_week)
    # Chia số nguyên rồi so với 0.7: 7/10 và hằng 0.7 cùng là số thực gần nhất của 0,7 nên so đúng.
    if total > 0 and max(last_week) / total >= BURST_SHARE:
        flags.append(Flag.BURST)
    if age_days < VERY_NEW_DAYS:
        flags.append(Flag.VERY_NEW)
    if description.strip() == "":
        flags.append(Flag.NO_DESCRIPTION)
    return tuple(flags)


def sparkline_points(series: Sequence[int], *, width: int = 120, height: int = 24) -> str:
    """Toạ độ cho thẻ `<polyline points="...">`: "x,y x,y …", cũ → mới, vẽ sẵn phía máy chủ.

    Trục y của SVG đi xuống nên 0 star nằm ở đáy (y = height), giá trị lớn nhất ở đỉnh (y = 0).
    Chuỗi toàn 0 vẽ thành đường ngang ở đáy.
    """
    peak = max(series, default=0)
    last_index = len(series) - 1
    points: list[str] = []
    for index, value in enumerate(series):
        x = index * width / last_index if last_index > 0 else 0.0
        y = height - value * height / peak if peak > 0 else float(height)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)
