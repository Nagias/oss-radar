"""Lượt hằng ngày, phần trending (F-011): repo từ 1.000 star cũng được lọc thô và xác minh.

Nhóm `rising` (dưới 1.000 star) và nhóm `trending` (từ 1.000 star) có ngân sách xác minh riêng: ngân
sách của rising không bao giờ bị tiêu cho repo lớn. GitHub giả có Search và lịch sử star.
"""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from pytest_django.fixtures import Settings

from features.rising import _common, services
from features.rising.models import DailyRun, RisingCheck, WatchQuery
from features.rising.tests.conftest import FakeGitHub, UseFake, days_ago, history, item, snapshot

pytestmark = pytest.mark.django_db

Status = DailyRun.Status
Source = RisingCheck.Source
Pool = RisingCheck.Pool

SMALL, BIG, MID_BIG, SLOW_GIANT, FORK_BIG, ARCHIVED_BIG, BOTH = 301, 401, 402, 403, 404, 405, 306


def run_daily_now() -> DailyRun:
    run = services.prepare_daily_run()
    services.execute_daily_run(run.pk)
    run.refresh_from_db()
    return run


def check_of(github_id: int) -> RisingCheck:
    return RisingCheck.objects.get(repository__github_id=github_id)


def histories() -> dict[int, list[dict[str, Any]]]:
    return {
        SMALL: history(dict.fromkeys(range(30), 10)),  # +70/7 ngày: rising, chưa tới 200
        BIG: history(dict.fromkeys(range(30), 50)),  # +350 trên ~4.650 star (7,5%): trending
        MID_BIG: history(dict.fromkeys(range(30), 10)),  # +70: chưa tới 200 → không trending
    }


def watched(use_fake: UseFake, *, extra: list[dict[str, Any]] | None = None) -> FakeGitHub:
    """Ảnh chụp 3 ngày trước rồi Search hôm nay: 1 ứng viên rising, 2 ứng viên trending.

    SMALL 560 → 600 (ước lượng 93), BIG 4.700 → 5.000 và MID_BIG 19.700 → 20.000 (cùng 700, trên
    1%); SLOW_GIANT 199.800 → 200.000 ước lượng 467 nhưng chỉ 0,23% → không phải ứng viên. Fork và
    repo lưu trữ không bao giờ được xét.
    """
    snapshot(SMALL, stars=560)
    snapshot(BIG, stars=4_700)
    snapshot(MID_BIG, stars=19_700)
    snapshot(SLOW_GIANT, stars=199_800)
    snapshot(FORK_BIG, stars=4_700)
    snapshot(ARCHIVED_BIG, stars=4_700)
    items = [
        item(SMALL, stars=600),
        item(BIG, stars=5_000),
        item(MID_BIG, stars=20_000),
        item(SLOW_GIANT, stars=200_000),
        item(FORK_BIG, stars=5_000, fork=True),
        item(ARCHIVED_BIG, stars=5_000, archived=True),
        *(extra or []),
    ]
    return use_fake(items, histories())


@pytest.fixture
def token(settings: Settings) -> None:
    settings.GITHUB_TOKEN = "test-token"


def test_screen_puts_big_repos_in_the_trending_pool(
    watch_list: list[WatchQuery], use_fake: UseFake, token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ngân sách 0 cho cả hai nhóm: giữ nguyên kết quả lọc thô để xem.
    monkeypatch.setattr(_common, "VERIFY_BUDGET_WITH_TOKEN", 0)
    monkeypatch.setattr(_common, "TRENDING_BUDGET_WITH_TOKEN", 0)
    fake = watched(use_fake)

    run = run_daily_now()

    rows = {
        check.repository.github_id: (check.pool, check.source, check.gain_7d)
        for check in RisingCheck.objects.select_related("repository")
    }
    assert rows == {
        SMALL: (Pool.RISING, Source.SNAPSHOT, 93),
        BIG: (Pool.TRENDING, Source.SNAPSHOT, 700),
        MID_BIG: (Pool.TRENDING, Source.SNAPSHOT, 700),
    }
    assert (run.candidate_count, run.trending_candidate_count) == (1, 2)
    assert run.unverified_count == 1  # chỉ đếm nhóm rising, như báo cáo /rising/
    assert fake.history.requested == []
    assert run.problems == [
        "Hết ngân sách xác minh — 1 ứng viên chưa xác minh.",
        "Hết ngân sách xác minh trending — 2 ứng viên trending chưa xác minh.",
    ]


def test_rising_budget_is_never_spent_on_trending_rows(
    watch_list: list[WatchQuery], use_fake: UseFake, token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ứng viên trending ước lượng 700 > ứng viên rising 93: lẫn nhóm thì lượt gọi duy nhất sẽ rơi
    # vào repo lớn.
    monkeypatch.setattr(_common, "VERIFY_BUDGET_WITH_TOKEN", 1)
    fake = watched(use_fake)

    run = run_daily_now()

    assert fake.history.requested == [SMALL, BIG, MID_BIG]
    assert (run.verify_budget, run.verify_calls_used) == (1, 1)
    assert (run.trending_budget, run.trending_calls_used) == (300, 2)


def test_trending_rows_are_verified_with_official_history(
    watch_list: list[WatchQuery], use_fake: UseFake, token: None
) -> None:
    watched(use_fake)

    run = run_daily_now()

    big, mid_big, small = check_of(BIG), check_of(MID_BIG), check_of(SMALL)
    assert (big.source, big.gain_7d, big.is_trending, big.is_rising) == (
        Source.HISTORY,
        350,
        True,
        False,
    )
    assert (mid_big.source, mid_big.gain_7d, mid_big.is_trending) == (Source.HISTORY, 70, False)
    assert (small.pool, small.is_rising, small.is_trending) == (Pool.RISING, True, False)
    assert (run.rising_count, run.trending_count, run.unverified_count) == (1, 1, 0)
    assert run.status == Status.SUCCEEDED
    assert run.step == DailyRun.Step.REPORT


def test_trending_budget_runs_out_with_a_note(
    watch_list: list[WatchQuery], use_fake: UseFake, token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_common, "TRENDING_BUDGET_WITH_TOKEN", 1)
    fake = watched(use_fake)

    run = run_daily_now()

    assert fake.history.requested == [SMALL, BIG]
    assert check_of(MID_BIG).source == Source.SNAPSHOT
    assert (run.trending_budget, run.trending_calls_used) == (1, 1)
    assert run.status == Status.SUCCEEDED_PARTIAL
    assert run.problems == ["Hết ngân sách xác minh trending — 1 ứng viên trending chưa xác minh."]


def test_stop_during_trending_still_reports_the_day(
    watch_list: list[WatchQuery], use_fake: UseFake, token: None
) -> None:
    # Trending chỉ làm giàu dữ liệu: bấm Dừng ở bước này không được làm mất báo cáo rising của ngày.
    fake = watched(use_fake)

    def press_stop(repo_id: int) -> int | None:
        if repo_id == BIG and not DailyRun.objects.filter(stop_requested=True).exists():
            services.request_daily_stop(DailyRun.objects.get())
        return None

    fake.history.fail_when = press_stop

    run = run_daily_now()

    assert fake.history.requested == [SMALL, BIG]
    assert (run.status, run.step) == (Status.SUCCEEDED_PARTIAL, DailyRun.Step.REPORT)
    assert services.latest_report_run() == run
    assert run.rising_count == 1
    assert check_of(MID_BIG).source == Source.SNAPSHOT
    assert (
        "Xác minh trending bị ngắt (bạn bấm Dừng) — 1 ứng viên trending chưa xác minh."
        in run.problems
    )


@pytest.mark.parametrize(
    ("status", "detail"),
    [(429, "GitHub hoặc mạng đang chặn"), (401, "GitHub từ chối token")],
)
def test_github_trouble_during_trending_still_reports_the_day(
    watch_list: list[WatchQuery], use_fake: UseFake, token: None, status: int, detail: str
) -> None:
    fake = watched(use_fake)
    fake.history.fail_when = lambda repo_id: status if repo_id == BIG else None

    run = run_daily_now()

    assert (run.status, run.step) == (Status.SUCCEEDED_PARTIAL, DailyRun.Step.REPORT)
    assert run.rising_count == 1
    assert MID_BIG not in fake.history.requested  # thôi gọi tiếp khi GitHub đã chặn
    assert any(note.startswith(f"Xác minh trending bị ngắt ({detail}") for note in run.problems)


def test_anonymous_trending_budget_setting_is_honoured(
    watch_list: list[WatchQuery], use_fake: UseFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ngân sách không token là cấu hình thật: đặt 1 thì máy không token cũng xác minh 1 repo.
    monkeypatch.setattr(_common, "TRENDING_BUDGET_ANONYMOUS", 1)
    fake = watched(use_fake)

    run = run_daily_now()

    assert fake.history.requested == [SMALL, BIG]
    assert (run.trending_budget, run.trending_calls_used) == (1, 1)


def test_trending_repo_gone_404_is_dropped(
    watch_list: list[WatchQuery], use_fake: UseFake, token: None
) -> None:
    fake = watched(use_fake)
    del fake.history.histories[BIG]  # repo bị xoá giữa lúc quét và lúc xác minh

    run = run_daily_now()

    assert not RisingCheck.objects.filter(repository__github_id=BIG).exists()
    assert check_of(MID_BIG).source == Source.HISTORY
    assert run.status == Status.SUCCEEDED
    assert run.trending_calls_used == 2


def test_no_token_skips_trending_verification_with_a_note(
    watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    fake = watched(use_fake)  # không đặt token: lượt chạy kiểu không token

    run = run_daily_now()

    assert fake.history.requested == [SMALL]
    assert check_of(BIG).source == Source.SNAPSHOT
    assert (run.trending_budget, run.trending_calls_used) == (0, 0)
    assert run.problems == ["Không có GITHUB_TOKEN — bỏ qua xác minh 2 ứng viên trending."]
    assert (run.status, run.step) == (Status.SUCCEEDED_PARTIAL, DailyRun.Step.REPORT)
    assert services.latest_report_run() == run


def test_run_paused_at_verify_continues_into_trending(
    watch_list: list[WatchQuery], use_fake: UseFake, token: None
) -> None:
    fake = watched(use_fake)
    fake.history.fail_when = lambda repo_id: 429 if repo_id == SMALL else None

    run = run_daily_now()

    assert (run.status, run.step) == (Status.PAUSED, DailyRun.Step.VERIFY)
    fake.history.fail_when = None
    DailyRun.objects.update(paused_at=timezone.now() - timedelta(minutes=16))
    continued = services.run_daily_if_due()

    assert continued is not None
    assert (continued.status, continued.step) == (Status.SUCCEEDED, DailyRun.Step.REPORT)
    assert check_of(BIG).source == Source.HISTORY
    assert continued.trending_count == 1


def test_small_repo_gaining_250_is_both_rising_and_trending(
    watch_list: list[WatchQuery], use_fake: UseFake, token: None
) -> None:
    snapshot(BOTH, stars=700)  # 700 → 800 trong 3 ngày: ứng viên rising (dưới 1.000 star)
    fake = watched(use_fake, extra=[item(BOTH, stars=800)])
    fake.history.histories[BOTH] = history(dict.fromkeys(range(30), 40))  # +280 trên 520 star

    run = run_daily_now()

    both = check_of(BOTH)
    assert (both.pool, both.is_rising, both.is_trending) == (Pool.RISING, True, True)
    assert (run.rising_count, run.trending_count) == (2, 2)
    assert days_ago(0) == run.day


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github
