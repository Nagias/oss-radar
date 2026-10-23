"""Công thức 3 điểm: Chất lượng, Tiềm năng, Nghi star giả (thiết kế F-006 mục 5, 6, 7).

Toàn hàm thuần: không đọc CSDL, không gọi mạng. Dữ kiện vào là dataclass do `services.py` gom từ
kho; mỗi điểm trả kèm từng thành phần và lời giải thích (nguyên tắc 6: không có hộp đen). Đổi trọng
số chỉ cần sửa hằng số ở đây, không cần migration (điểm tính lúc hiển thị, không lưu).

Mọi thành phần và tổng điểm là số nguyên. Ngưỡng là quyết định có căn cứ đo thật (thiết kế mục 2),
sẽ chỉnh sau vài tuần chạy.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from django.utils import formats

# --- Chất lượng (0-100) ----------------------------------------------------------------------
POPULARITY_MAX = 30  # 30 * log10(star/10)/3: 10 star → 0, 100 → 10, 1.000 → 20, 10.000 → 30
COMMUNITY_MAX = 20
COMMUNITY_FORK_HIGH = (5, 15)  # fork/star từ 5% → 15 điểm
COMMUNITY_FORK_LOW = (2, 8)  # từ 2% → 8 điểm
COMMUNITY_ISSUES_POINTS = 5  # có issue/PR đang mở: có người dùng thật đang báo lỗi, góp code
ACTIVITY_MAX = 20
ACTIVITY_STEPS = ((30, 20), (90, 12), (365, 5))  # (đẩy code trong N ngày, điểm)
ORGANIZATION_POINTS = 15  # F-003 sẽ cộng thêm "tổ chức uy tín"
HYGIENE_POINTS = 5  # mỗi mục: giấy phép, mô tả, từ 3 chủ đề
HYGIENE_MIN_TOPICS = 3

# --- Tiềm năng (0-100) -----------------------------------------------------------------------
SPEED_MAX = 40  # 40 * log10(tăng 7 ngày/10)/2: +10 → 0, +100 → 20, +1.000 → 40
RELATIVE_MAX = 20
RELATIVE_STEPS = ((100, 20), (30, 12), (10, 6))  # (tăng từ N% so với 7 ngày trước, điểm)
ROOM_MAX = 20
ROOM_STEPS = ((1000, 20), (5000, 10))  # (dưới N star, điểm)
MOMENTUM_MAX = 20
STEADY_DAYS = 5  # có star ở ít nhất 5/7 ngày → 10 điểm
STEADY_POINTS = 10
SUSTAINED_RATIO = 2  # tăng 30 ngày ≥ 2 * tăng 7 ngày (đã tăng hơn một tuần) → 10 điểm
SUSTAINED_POINTS = 10
WEEK_DAYS = 7

# --- Nghi star giả (cộng dồn) ----------------------------------------------------------------
SUSPICION_MIN_STARS = 100
# (fork dưới N phần nghìn của star, điểm, chữ hiển thị). Đo trên 32.412 repo: repo thật cỡ vài
# trăm star trở lên hầu như luôn có fork.
FORK_RATIO_STEPS = ((5, 45, "0,5%"), (10, 35, "1%"), (20, 20, "2%"))
MORE_FORKS_POINTS = 15
NO_COMMIT_POINTS = 20
BURST_POINTS = 15
BURST_SHARE = 0.7  # cùng giá trị với rising.growth.BURST_SHARE (có test chéo)
BURST_MIN_GAIN = 100
NEW_OWNER_DAYS = 90
NEW_OWNER_POINTS = 20
FEW_REPOS_MAX = 2
FEW_REPOS_POINTS = 10
VETERAN_DAYS = 730
VETERAN_FOLLOWERS = 50
VETERAN_POINTS = -15
REVIEW_FROM = 30
HIGH_FROM = 60


@dataclass(frozen=True, slots=True)
class RepoFacts:
    """Số liệu của repo lấy từ kho (đều từ API chính thức của GitHub)."""

    stars: int
    forks: int
    open_issues: int | None  # None = chưa biết
    is_organization: bool
    license_spdx: str
    description: str
    topic_count: int
    is_archived: bool
    created_at: datetime
    pushed_at: datetime | None


@dataclass(frozen=True, slots=True)
class GrowthFacts:
    """Số tăng star do bên gọi truyền vào. `series`: star mới từng ngày, cũ → mới (có thể rỗng)."""

    stars: int
    gain_7d: int
    gain_30d: int | None
    series: tuple[int, ...]
    estimated: bool


@dataclass(frozen=True, slots=True)
class OwnerFacts:
    """Hồ sơ chủ repo đã lấy từ GitHub."""

    created_at: datetime
    followers: int
    public_repos: int


@dataclass(frozen=True, slots=True)
class Component:
    label: str
    points: int
    max_points: int
    detail: str


@dataclass(frozen=True, slots=True)
class Score:
    total: int
    components: tuple[Component, ...]
    notes: tuple[str, ...] = ()
    estimated: bool = False


class SuspicionLevel(StrEnum):
    NOT_SCORED = "not_scored"
    CLEAR = "clear"
    REVIEW = "review"
    HIGH = "high"


LEVEL_LABELS: dict[SuspicionLevel, str] = {
    SuspicionLevel.NOT_SCORED: "Chưa xét",
    SuspicionLevel.CLEAR: "Không nghi",
    SuspicionLevel.REVIEW: "Cần xem",
    SuspicionLevel.HIGH: "Nghi cao",
}


@dataclass(frozen=True, slots=True)
class Signal:
    points: int
    reason: str


@dataclass(frozen=True, slots=True)
class Suspicion:
    level: SuspicionLevel
    points: int
    signals: tuple[Signal, ...]
    notes: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return LEVEL_LABELS[self.level]

    @property
    def is_hidden(self) -> bool:
        """ "Nghi cao" bị ẩn mặc định (có nút hiện lại)."""
        return self.level == SuspicionLevel.HIGH


# --- Chất lượng ------------------------------------------------------------------------------


def quality_score(repo: RepoFacts, *, now: datetime) -> Score:
    components = (
        _popularity(repo.stars),
        _community(repo),
        _activity(repo.pushed_at, now=now),
        _organization(repo.is_organization),
        _hygiene(repo),
    )
    total = sum(component.points for component in components)
    if not repo.is_archived:
        return Score(total, components)
    return Score(
        total // 2, components, notes=("đã lưu trữ — không còn phát triển: tổng điểm chia đôi",)
    )


def _popularity(stars: int) -> Component:
    raw = POPULARITY_MAX * math.log10(stars / 10) / 3 if stars > 10 else 0.0
    return Component("Phổ biến", _clip(raw, POPULARITY_MAX), POPULARITY_MAX, f"{_n(stars)} star")


def _community(repo: RepoFacts) -> Component:
    points = 0
    detail = f"{_n(repo.forks)} fork"
    if repo.stars > 0:
        per_100 = repo.forks * 100 / repo.stars
        detail += f" ({_decimal(per_100)} fork/100 star)"
        for percent, step_points in (COMMUNITY_FORK_HIGH, COMMUNITY_FORK_LOW):
            if repo.forks * 100 >= repo.stars * percent:
                points = step_points
                break
    if repo.open_issues is None:
        detail += " · chưa có số issue/PR đang mở"
    elif repo.open_issues > 0:
        points += COMMUNITY_ISSUES_POINTS
        detail += f" · {_n(repo.open_issues)} issue/PR đang mở"
    else:
        detail += " · không có issue/PR đang mở"
    return Component("Cộng đồng", points, COMMUNITY_MAX, detail)


def _activity(pushed_at: datetime | None, *, now: datetime) -> Component:
    if pushed_at is None:
        return Component("Còn phát triển", 0, ACTIVITY_MAX, "chưa có ngày đẩy code")
    days = (now - pushed_at).days
    points = next((p for limit, p in ACTIVITY_STEPS if days <= limit), 0)
    return Component("Còn phát triển", points, ACTIVITY_MAX, f"đẩy code {days} ngày trước")


def _organization(is_organization: bool) -> Component:
    if is_organization:
        return Component(
            "Tổ chức đứng sau", ORGANIZATION_POINTS, ORGANIZATION_POINTS, "chủ repo là tổ chức"
        )
    return Component("Tổ chức đứng sau", 0, ORGANIZATION_POINTS, "chủ repo là cá nhân")


def _hygiene(repo: RepoFacts) -> Component:
    has_license = repo.license_spdx != ""
    has_description = repo.description.strip() != ""
    enough_topics = repo.topic_count >= HYGIENE_MIN_TOPICS
    points = HYGIENE_POINTS * sum((has_license, has_description, enough_topics))
    detail = " · ".join(
        (
            f"giấy phép {repo.license_spdx}" if has_license else "không giấy phép",
            "có mô tả" if has_description else "không mô tả",
            f"{repo.topic_count} chủ đề",
        )
    )
    return Component("Chuẩn mực", points, 3 * HYGIENE_POINTS, detail)


# --- Tiềm năng -------------------------------------------------------------------------------


def potential_score(growth: GrowthFacts) -> Score:
    components = (
        _speed(growth.gain_7d),
        _relative(growth.stars, growth.gain_7d),
        _room(growth.stars),
        _momentum(growth),
    )
    total = sum(component.points for component in components)
    if not growth.estimated:
        return Score(total, components)
    return Score(
        total,
        components,
        notes=("số tăng là ước lượng từ ảnh chụp star, chưa xác minh",),
        estimated=True,
    )


def _speed(gain_7d: int) -> Component:
    raw = SPEED_MAX * math.log10(gain_7d / 10) / 2 if gain_7d > 10 else 0.0
    return Component(
        "Tốc độ", _clip(raw, SPEED_MAX), SPEED_MAX, f"{_signed(gain_7d)} star trong 7 ngày"
    )


def _relative(stars: int, gain_7d: int) -> Component:
    before = stars - gain_7d
    if before <= 0:
        detail = f"toàn bộ {_n(stars)} star đến trong 7 ngày"
        return Component("Tăng tương đối", RELATIVE_MAX, RELATIVE_MAX, detail)
    # So bằng số nguyên: tăng ≥ N% của số star 7 ngày trước ⇔ tăng * 100 ≥ trước * N.
    points = next((p for percent, p in RELATIVE_STEPS if gain_7d * 100 >= before * percent), 0)
    detail = f"{_signed(round(gain_7d * 100 / before))}% so với 7 ngày trước ({_n(before)} star)"
    return Component("Tăng tương đối", points, RELATIVE_MAX, detail)


def _room(stars: int) -> Component:
    points = next((p for limit, p in ROOM_STEPS if stars < limit), 0)
    return Component("Còn chỗ lớn", points, ROOM_MAX, f"đang {_n(stars)} star")


def _momentum(growth: GrowthFacts) -> Component:
    if len(growth.series) < WEEK_DAYS:
        return Component("Đà bền", 0, MOMENTUM_MAX, "chưa có số liệu theo ngày")
    active = sum(1 for stars in growth.series[-WEEK_DAYS:] if stars > 0)
    points = STEADY_POINTS if active >= STEADY_DAYS else 0
    detail = f"{active}/7 ngày có star"
    if growth.gain_30d is not None:
        detail += f" · {_signed(growth.gain_30d)} trong 30 ngày"
        if growth.gain_7d > 0 and growth.gain_30d >= SUSTAINED_RATIO * growth.gain_7d:
            points += SUSTAINED_POINTS
    return Component("Đà bền", points, MOMENTUM_MAX, detail)


# --- Nghi star giả ---------------------------------------------------------------------------


def suspicion_score(
    repo: RepoFacts,
    *,
    growth: GrowthFacts | None,
    owner: OwnerFacts | None,
    owner_missing: bool,
    now: datetime,
) -> Suspicion:
    """Cộng dồn tín hiệu đáng ngờ; tín hiệu tốt (chủ lâu năm, có người theo dõi) trừ điểm.

    Không tín hiệu đơn lẻ nào đủ tới ngưỡng ẩn (60): fork thấp nhất cũng chỉ 45.
    """
    if repo.stars < SUSPICION_MIN_STARS:
        return Suspicion(
            SuspicionLevel.NOT_SCORED, 0, (), notes=("dưới 100 star — chưa đủ dữ kiện để xét",)
        )
    signals = [*_repo_signals(repo), *_growth_signals(growth)]
    notes: tuple[str, ...] = ()
    if owner is not None:
        signals.extend(_owner_signals(owner, repo_created=repo.created_at, now=now))
    elif owner_missing:
        notes = ("tài khoản chủ repo không còn tồn tại trên GitHub",)
    else:
        notes = ("chưa có hồ sơ chủ repo — chưa tính phần hồ sơ chủ",)
    points = max(0, sum(signal.points for signal in signals))
    return Suspicion(suspicion_level(points), points, tuple(signals), notes)


def suspicion_level(points: int) -> SuspicionLevel:
    if points >= HIGH_FROM:
        return SuspicionLevel.HIGH
    if points >= REVIEW_FROM:
        return SuspicionLevel.REVIEW
    return SuspicionLevel.CLEAR


def _repo_signals(repo: RepoFacts) -> list[Signal]:
    signals: list[Signal] = []
    # So bằng số nguyên: fork dưới N phần nghìn của star ⇔ fork * 1000 < star * N.
    for per_mille, points, label in FORK_RATIO_STEPS:
        if repo.forks * 1000 < repo.stars * per_mille:
            reason = (
                f"{_n(repo.forks)} fork trên {_n(repo.stars)} star (dưới {label}) — "
                "repo thật cỡ này hầu như luôn có fork"
            )
            signals.append(Signal(points, reason))
            break
    if repo.forks > repo.stars:
        signals.append(Signal(MORE_FORKS_POINTS, "fork nhiều hơn star — bất thường"))
    if repo.pushed_at is not None and _utc_day(repo.pushed_at) == _utc_day(repo.created_at):
        signals.append(Signal(NO_COMMIT_POINTS, "không có commit nào sau ngày tạo"))
    return signals


def _growth_signals(growth: GrowthFacts | None) -> list[Signal]:
    if growth is None or len(growth.series) < WEEK_DAYS or growth.gain_7d < BURST_MIN_GAIN:
        return []
    last_week: Sequence[int] = growth.series[-WEEK_DAYS:]
    total = sum(last_week)
    peak = max(last_week)
    if total > 0 and peak / total >= BURST_SHARE:
        return [Signal(BURST_POINTS, f"{_n(peak)} star đến trong một ngày")]
    return []


def _owner_signals(owner: OwnerFacts, *, repo_created: datetime, now: datetime) -> list[Signal]:
    signals: list[Signal] = []
    gap = repo_created - owner.created_at
    # Khoảng cách âm: repo được chuyển sang tài khoản tạo sau repo — không phải dấu hiệu mua star.
    if timedelta(0) <= gap < timedelta(days=NEW_OWNER_DAYS):
        signals.append(
            Signal(NEW_OWNER_POINTS, f"tài khoản chủ mới tạo {gap.days} ngày trước repo")
        )
    if owner.public_repos <= FEW_REPOS_MAX:
        signals.append(
            Signal(FEW_REPOS_POINTS, f"chủ repo chỉ có {owner.public_repos} repo công khai")
        )
    age_days = (now - owner.created_at).days
    if age_days >= VETERAN_DAYS and owner.followers >= VETERAN_FOLLOWERS:
        reason = f"chủ repo lâu năm ({age_days // 365} năm), {_n(owner.followers)} người theo dõi"
        signals.append(Signal(VETERAN_POINTS, reason))
    return signals


# --- Hàm phụ ---------------------------------------------------------------------------------


def _clip(raw: float, upper: int) -> int:
    return max(0, min(upper, round(raw)))


def _utc_day(moment: datetime) -> date:
    return moment.astimezone(UTC).date()


def _n(value: int) -> str:
    """Số kiểu Việt Nam, có dấu ngăn nghìn "." (1.000)."""
    return formats.number_format(value, force_grouping=True)


def _signed(value: int) -> str:
    return f"+{_n(value)}" if value >= 0 else f"−{_n(-value)}"  # noqa: RUF001


def _decimal(value: float) -> str:
    """Một chữ số thập phân khi dưới 10 (7,1), số nguyên khi từ 10 (11)."""
    if value >= 10 or value == int(value):
        return _n(round(value))
    return formats.number_format(round(value, 1), decimal_pos=1)
