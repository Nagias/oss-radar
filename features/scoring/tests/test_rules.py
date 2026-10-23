"""Công thức chấm điểm: hàm thuần, kiểm từng thành phần ở các mốc biên bằng số tính tay.

Mỗi điểm phải giải thích được (nguyên tắc 6): test kiểm cả con số lẫn lời giải thích đi kèm.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from features.scoring import rules
from features.scoring.rules import (
    GrowthFacts,
    OwnerFacts,
    RepoFacts,
    Score,
    Suspicion,
    SuspicionLevel,
    potential_score,
    quality_score,
    suspicion_score,
)

NOW = datetime(2026, 10, 23, 3, 0, tzinfo=UTC)

BASE = RepoFacts(
    stars=1000,
    forks=100,
    open_issues=5,
    is_organization=False,
    license_spdx="",
    description="",
    topic_count=0,
    is_archived=False,
    created_at=datetime(2024, 1, 10, 9, 0, tzinfo=UTC),
    pushed_at=NOW - timedelta(days=400),
)


def repo(**changes: object) -> RepoFacts:
    return replace(BASE, **changes)  # type: ignore[arg-type]


def part(score: Score, label: str) -> rules.Component:
    [found] = [component for component in score.components if component.label == label]
    return found


# --- Chất lượng ------------------------------------------------------------------------------


def quality(**changes: object) -> Score:
    return quality_score(repo(**changes), now=NOW)


@pytest.mark.parametrize(
    ("stars", "points"),
    [(0, 0), (9, 0), (10, 0), (100, 10), (316, 15), (1000, 20), (10_000, 30), (250_000, 30)],
)
def test_popularity_follows_log_of_stars(stars: int, points: int) -> None:
    popularity = part(quality(stars=stars, forks=0), "Phổ biến")

    assert (popularity.points, popularity.max_points) == (points, 30)


def test_popularity_explains_star_count() -> None:
    assert part(quality(stars=1234), "Phổ biến").detail == "1.234 star"


@pytest.mark.parametrize(
    ("forks", "points"), [(0, 0), (19, 0), (20, 8), (49, 8), (50, 15), (900, 15)]
)
def test_community_follows_fork_ratio(forks: int, points: int) -> None:
    community = part(quality(stars=1000, forks=forks, open_issues=0), "Cộng đồng")

    assert (community.points, community.max_points) == (points, 20)


def test_community_adds_points_for_open_issues() -> None:
    community = part(quality(stars=1000, forks=71, open_issues=3), "Cộng đồng")

    assert community.points == 20
    assert community.detail == "71 fork (7,1 fork/100 star) · 3 issue/PR đang mở"


def test_community_says_when_issue_count_is_unknown_or_zero() -> None:
    unknown = part(quality(forks=110, open_issues=None), "Cộng đồng")
    none_open = part(quality(forks=110, open_issues=0), "Cộng đồng")

    assert unknown.points == none_open.points == 15
    assert unknown.detail == "110 fork (11 fork/100 star) · chưa có số issue/PR đang mở"
    assert none_open.detail == "110 fork (11 fork/100 star) · không có issue/PR đang mở"


def test_community_of_repo_without_stars_has_no_ratio() -> None:
    community = part(quality(stars=0, forks=0, open_issues=0), "Cộng đồng")

    assert community.points == 0
    assert community.detail == "0 fork · không có issue/PR đang mở"


@pytest.mark.parametrize(
    ("days", "points"),
    [(0, 20), (30, 20), (31, 12), (90, 12), (91, 5), (365, 5), (366, 0)],
)
def test_activity_follows_last_push(days: int, points: int) -> None:
    activity = part(quality(pushed_at=NOW - timedelta(days=days, hours=1)), "Còn phát triển")

    assert (activity.points, activity.max_points) == (points, 20)
    assert activity.detail == f"đẩy code {days} ngày trước"


def test_activity_without_push_date_scores_zero() -> None:
    activity = part(quality(pushed_at=None), "Còn phát triển")

    assert (activity.points, activity.detail) == (0, "chưa có ngày đẩy code")


def test_organization_owner_scores_points() -> None:
    assert part(quality(is_organization=True), "Tổ chức đứng sau").points == 15
    person = part(quality(is_organization=False), "Tổ chức đứng sau")
    assert (person.points, person.max_points, person.detail) == (0, 15, "chủ repo là cá nhân")


def test_hygiene_counts_license_description_and_topics() -> None:
    full = part(quality(license_spdx="MIT", description="Một công cụ", topic_count=3), "Chuẩn mực")
    empty = part(quality(license_spdx="", description="   ", topic_count=2), "Chuẩn mực")

    assert (full.points, full.max_points) == (15, 15)
    assert full.detail == "giấy phép MIT · có mô tả · 3 chủ đề"
    assert empty.points == 0
    assert empty.detail == "không giấy phép · không mô tả · 2 chủ đề"


def test_unrecognised_license_file_still_counts() -> None:
    assert part(quality(license_spdx="NOASSERTION"), "Chuẩn mực").points == 5


def test_quality_total_is_sum_of_components() -> None:
    score = quality(
        stars=1000,
        forks=100,
        open_issues=2,
        pushed_at=NOW - timedelta(days=3),
        is_organization=True,
        license_spdx="MIT",
        description="x",
        topic_count=5,
    )

    assert [c.points for c in score.components] == [20, 20, 20, 15, 15]
    assert score.total == 90
    assert score.notes == ()


def test_archived_repo_total_is_halved_rounding_down() -> None:
    score = quality(stars=1000, forks=0, open_issues=0, pushed_at=None, license_spdx="MIT")

    archived = quality(
        stars=1000, forks=0, open_issues=0, pushed_at=None, license_spdx="MIT", is_archived=True
    )

    assert score.total == 25
    assert archived.total == 12
    assert archived.notes == ("đã lưu trữ — không còn phát triển: tổng điểm chia đôi",)


# --- Tiềm năng --------------------------------------------------------------------------------


def growth(
    *,
    stars: int = 500,
    gain_7d: int = 100,
    gain_30d: int | None = 150,
    series: tuple[int, ...] | None = None,
    estimated: bool = False,
) -> GrowthFacts:
    if series is None:
        series = (0,) * 23 + (20, 20, 20, 20, 20, 0, 0)
    return GrowthFacts(
        stars=stars, gain_7d=gain_7d, gain_30d=gain_30d, series=series, estimated=estimated
    )


@pytest.mark.parametrize(
    ("gain", "points"),
    [(-30, 0), (0, 0), (10, 0), (100, 20), (316, 30), (1000, 40), (5000, 40)],
)
def test_speed_follows_log_of_weekly_gain(gain: int, points: int) -> None:
    speed = part(potential_score(growth(stars=5000, gain_7d=gain)), "Tốc độ")

    assert (speed.points, speed.max_points) == (points, 40)


@pytest.mark.parametrize(
    ("stars", "gain", "points"),
    [(1090, 90, 0), (1100, 100, 6), (1299, 299, 6), (1300, 300, 12), (2000, 1000, 20)],
)
def test_relative_growth_compares_with_stars_a_week_ago(stars: int, gain: int, points: int) -> None:
    relative = part(potential_score(growth(stars=stars, gain_7d=gain)), "Tăng tương đối")

    assert (relative.points, relative.max_points) == (points, 20)


def test_relative_growth_explains_percent() -> None:
    relative = part(potential_score(growth(stars=1300, gain_7d=300)), "Tăng tương đối")

    assert relative.detail == "+30% so với 7 ngày trước (1.000 star)"


def test_all_stars_within_the_week_counts_as_full_relative_growth() -> None:
    relative = part(potential_score(growth(stars=120, gain_7d=120)), "Tăng tương đối")

    assert relative.points == 20
    assert relative.detail == "toàn bộ 120 star đến trong 7 ngày"


@pytest.mark.parametrize(("stars", "points"), [(999, 20), (1000, 10), (4999, 10), (5000, 0)])
def test_room_to_grow_follows_current_stars(stars: int, points: int) -> None:
    room = part(potential_score(growth(stars=stars)), "Còn chỗ lớn")

    assert (room.points, room.max_points, room.detail) == (
        points,
        20,
        f"đang {stars:,} star".replace(",", "."),
    )


def test_steady_momentum_needs_five_active_days_and_a_longer_run() -> None:
    four_days = (0,) * 23 + (25, 25, 25, 25, 0, 0, 0)
    five_days = (0,) * 23 + (20, 20, 20, 20, 20, 0, 0)

    short = part(potential_score(growth(series=four_days, gain_30d=150)), "Đà bền")
    steady = part(potential_score(growth(series=five_days, gain_30d=199)), "Đà bền")
    long_run = part(potential_score(growth(series=five_days, gain_30d=200)), "Đà bền")

    assert (short.points, short.max_points) == (0, 20)
    assert short.detail == "4/7 ngày có star · +150 trong 30 ngày"
    assert steady.points == 10
    assert long_run.points == 20


def test_estimated_growth_has_no_daily_series() -> None:
    score = potential_score(growth(series=(), gain_30d=None, estimated=True))

    momentum = part(score, "Đà bền")
    assert (momentum.points, momentum.detail) == (0, "chưa có số liệu theo ngày")
    assert score.estimated is True
    assert score.notes == ("số tăng là ước lượng từ ảnh chụp star, chưa xác minh",)


def test_potential_total_is_sum_of_components() -> None:
    score = potential_score(growth(stars=640, gain_7d=100, gain_30d=150))

    assert [c.points for c in score.components] == [20, 6, 20, 10]
    assert score.total == 56


# --- Nghi star giả ----------------------------------------------------------------------------

CLEAN = repo(
    stars=1000,
    forks=100,
    created_at=datetime(2025, 1, 1, 9, 0, tzinfo=UTC),
    pushed_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
)


def suspicion(
    facts: RepoFacts = CLEAN,
    *,
    growth_facts: GrowthFacts | None = None,
    owner: OwnerFacts | None = None,
    owner_missing: bool = False,
) -> Suspicion:
    return suspicion_score(
        facts, growth=growth_facts, owner=owner, owner_missing=owner_missing, now=NOW
    )


def reasons(result: Suspicion) -> list[tuple[int, str]]:
    return [(signal.points, signal.reason) for signal in result.signals]


def test_clean_repo_is_not_suspicious() -> None:
    result = suspicion()

    assert (result.level, result.points, result.signals) == (SuspicionLevel.CLEAR, 0, ())
    assert result.label == "Không nghi"


def test_repo_under_100_stars_is_not_scored() -> None:
    result = suspicion(replace(CLEAN, stars=99, forks=0))

    assert result.level == SuspicionLevel.NOT_SCORED
    assert result.signals == ()
    assert result.notes == ("dưới 100 star — chưa đủ dữ kiện để xét",)


@pytest.mark.parametrize(
    ("forks", "points", "limit"),
    [
        (4, 45, "0,5%"),
        (5, 35, "1%"),
        (9, 35, "1%"),
        (10, 20, "2%"),
        (19, 20, "2%"),
    ],
)
def test_few_forks_for_the_stars_is_suspicious(forks: int, points: int, limit: str) -> None:
    result = suspicion(replace(CLEAN, stars=1000, forks=forks))

    assert reasons(result) == [
        (
            points,
            f"{forks} fork trên 1.000 star (dưới {limit}) — repo thật cỡ này hầu như luôn có fork",
        )
    ]


def test_two_percent_forks_is_fine() -> None:
    assert suspicion(replace(CLEAN, stars=1000, forks=20)).signals == ()


def test_more_forks_than_stars_is_unusual() -> None:
    result = suspicion(replace(CLEAN, stars=541, forks=597))

    assert reasons(result) == [(15, "fork nhiều hơn star — bất thường")]


def test_no_commit_after_creation_day_is_suspicious() -> None:
    created = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
    same_day = replace(CLEAN, created_at=created, pushed_at=created + timedelta(hours=22))
    next_day = replace(CLEAN, created_at=created, pushed_at=created + timedelta(hours=23))

    assert reasons(suspicion(same_day)) == [(20, "không có commit nào sau ngày tạo")]
    assert suspicion(next_day).signals == ()
    assert suspicion(replace(CLEAN, pushed_at=None)).signals == ()


def burst(gain_7d: int) -> GrowthFacts:
    # 70% số tăng 7 ngày dồn vào một ngày.
    peak = gain_7d * 7 // 10
    rest = gain_7d - peak
    series = (0,) * 23 + (peak, rest, 0, 0, 0, 0, 0)
    return GrowthFacts(stars=900, gain_7d=gain_7d, gain_30d=gain_7d, series=series, estimated=False)


def test_burst_of_stars_in_one_day_is_suspicious_from_100_gain() -> None:
    assert reasons(suspicion(growth_facts=burst(100))) == [(15, "70 star đến trong một ngày")]
    assert suspicion(growth_facts=burst(90)).signals == ()


def test_burst_needs_daily_series() -> None:
    estimated = GrowthFacts(stars=900, gain_7d=500, gain_30d=None, series=(), estimated=True)

    assert suspicion(growth_facts=estimated).signals == ()


def owner(
    *, created: datetime = datetime(2018, 1, 1, tzinfo=UTC), followers: int = 10, repos: int = 30
) -> OwnerFacts:
    return OwnerFacts(created_at=created, followers=followers, public_repos=repos)


def test_owner_account_made_shortly_before_the_repo_is_suspicious() -> None:
    created = CLEAN.created_at
    young = owner(created=created - timedelta(days=89, hours=23))
    older = owner(created=created - timedelta(days=90))

    assert reasons(suspicion(owner=young)) == [(20, "tài khoản chủ mới tạo 89 ngày trước repo")]
    assert suspicion(owner=older).signals == ()


def test_owner_account_newer_than_repo_is_ignored() -> None:
    # Repo được chuyển sang một tài khoản tạo sau repo: không phải dấu hiệu mua star.
    newer = owner(created=CLEAN.created_at + timedelta(days=10))

    assert suspicion(owner=newer).signals == ()


def test_owner_with_few_public_repos_is_suspicious() -> None:
    assert reasons(suspicion(owner=owner(repos=2))) == [(10, "chủ repo chỉ có 2 repo công khai")]
    assert suspicion(owner=owner(repos=3)).signals == ()


def test_long_standing_followed_owner_lowers_suspicion() -> None:
    # Repo tạo gần đây: tài khoản chủ (2 năm tuổi) không bị coi là "mới tạo trước repo".
    few_forks = replace(CLEAN, forks=4, created_at=NOW - timedelta(days=100))
    veteran = owner(created=NOW - timedelta(days=730), followers=50)

    result = suspicion(few_forks, owner=veteran)

    assert result.points == 30
    assert reasons(result)[-1] == (-15, "chủ repo lâu năm (2 năm), 50 người theo dõi")
    assert suspicion(few_forks, owner=replace(veteran, followers=49)).points == 45
    younger = replace(veteran, created_at=NOW - timedelta(days=729))
    assert suspicion(few_forks, owner=younger).points == 45


def test_points_never_go_negative() -> None:
    veteran = owner(created=NOW - timedelta(days=3000), followers=900)

    result = suspicion(owner=veteran)

    assert result.points == 0
    assert result.level == SuspicionLevel.CLEAR


def test_notes_say_whether_owner_profile_was_used() -> None:
    assert suspicion().notes == ("chưa có hồ sơ chủ repo — chưa tính phần hồ sơ chủ",)
    assert suspicion(owner_missing=True).notes == (
        "tài khoản chủ repo không còn tồn tại trên GitHub",
    )
    assert suspicion(owner=owner()).notes == ()


@pytest.mark.parametrize(
    ("forks", "created_same_day", "level"),
    [
        (20, False, SuspicionLevel.CLEAR),  # 0 điểm
        (10, True, SuspicionLevel.REVIEW),  # 20 + 20 = 40
        (19, False, SuspicionLevel.CLEAR),  # 20
        (5, False, SuspicionLevel.REVIEW),  # 35
        (4, False, SuspicionLevel.REVIEW),  # 45: một tín hiệu đơn lẻ không đủ để ẩn
        (4, True, SuspicionLevel.HIGH),  # 45 + 20 = 65
    ],
)
def test_levels_follow_thresholds(forks: int, created_same_day: bool, level: str) -> None:
    facts = replace(CLEAN, forks=forks)
    if created_same_day:
        facts = replace(facts, pushed_at=facts.created_at)

    assert suspicion(facts).level == level


def test_level_boundaries() -> None:
    assert rules.suspicion_level(29) == SuspicionLevel.CLEAR
    assert rules.suspicion_level(30) == SuspicionLevel.REVIEW
    assert rules.suspicion_level(59) == SuspicionLevel.REVIEW
    assert rules.suspicion_level(60) == SuspicionLevel.HIGH
    assert rules.LEVEL_LABELS[SuspicionLevel.REVIEW] == "Cần xem"
    assert rules.LEVEL_LABELS[SuspicionLevel.HIGH] == "Nghi cao"


# --- Ba ví dụ thật ở mục 2 của thiết kế (đo 2026-10-23) ----------------------------------------


def test_real_example_genspark_claw_is_high() -> None:
    created = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)
    facts = replace(CLEAN, stars=613, forks=2, created_at=created, pushed_at=created)
    profile = OwnerFacts(created_at=datetime(2026, 3, 2, tzinfo=UTC), followers=0, public_repos=2)

    without_owner = suspicion(facts)
    with_owner = suspicion(facts, owner=profile)

    assert (without_owner.points, without_owner.level) == (65, SuspicionLevel.HIGH)
    assert (with_owner.points, with_owner.level) == (75, SuspicionLevel.HIGH)


def test_real_example_xop01_drops_to_review_with_owner_profile() -> None:
    created = datetime(2026, 9, 25, 2, 0, tzinfo=UTC)
    facts = replace(CLEAN, stars=637, forks=0, created_at=created, pushed_at=created)
    profile = OwnerFacts(
        created_at=datetime(2020, 4, 12, tzinfo=UTC), followers=73, public_repos=41
    )

    assert suspicion(facts).points == 65
    with_owner = suspicion(facts, owner=profile)
    assert (with_owner.points, with_owner.level) == (50, SuspicionLevel.REVIEW)


def test_real_example_git_ai_is_clear() -> None:
    facts = replace(
        CLEAN,
        stars=968,
        forks=91,
        created_at=datetime(2026, 8, 30, tzinfo=UTC),
        pushed_at=datetime(2026, 10, 21, tzinfo=UTC),
    )
    profile = OwnerFacts(
        created_at=datetime(2017, 6, 1, tzinfo=UTC), followers=2400, public_repos=60
    )

    assert suspicion(facts, owner=profile).level == SuspicionLevel.CLEAR
