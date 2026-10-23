"""Giãn nhịp và ngân sách: không dội request, chờ đúng lúc GitHub hồi lượt, không tiêu lố."""

from datetime import UTC, datetime

import pytest

from integrations.github.errors import GitHubRateLimitError
from integrations.github.pacing import (
    CallBudget,
    CallBudgetExhaustedError,
    RequestPacer,
    select_min_interval,
)
from tests.fakes import FakeTime


def make_pacer(clock: FakeTime, *, min_interval: float = 2.1) -> RequestPacer:
    return RequestPacer(
        min_interval=min_interval,
        sleep=clock.sleep,
        clock=clock.monotonic,
        wall_clock=clock.time,
        jitter=lambda: 0.0,
    )


def test_budget_allows_exactly_limit_calls() -> None:
    budget = CallBudget(2)

    budget.take()
    budget.take()

    assert (budget.used, budget.remaining) == (2, 0)
    with pytest.raises(CallBudgetExhaustedError):
        budget.take()


def test_zero_budget_refuses_first_call() -> None:
    with pytest.raises(CallBudgetExhaustedError):
        CallBudget(0).take()


def test_first_request_does_not_wait(fake_time: FakeTime) -> None:
    make_pacer(fake_time).before_request()

    assert fake_time.sleeps == []


def test_requests_are_spaced_by_min_interval(fake_time: FakeTime) -> None:
    pacer = make_pacer(fake_time)
    pacer.before_request()
    fake_time.sleep(0.5)  # 0,5 giây trôi qua giữa hai lượt gọi
    fake_time.sleeps.clear()

    pacer.before_request()

    assert fake_time.sleeps == [pytest.approx(1.6)]


def test_no_wait_when_interval_already_passed(fake_time: FakeTime) -> None:
    pacer = make_pacer(fake_time)
    pacer.before_request()
    fake_time.sleep(5.0)
    fake_time.sleeps.clear()

    pacer.before_request()

    assert fake_time.sleeps == []


def test_waits_until_reset_after_quota_exhausted(fake_time: FakeTime) -> None:
    pacer = make_pacer(fake_time)
    pacer.before_request()
    pacer.record_response(remaining=0, reset_epoch=int(fake_time.time()) + 30)

    pacer.before_request()

    assert fake_time.sleeps == [pytest.approx(31, abs=1)]


def test_rate_limit_wait_prefers_retry_after(fake_time: FakeTime) -> None:
    make_pacer(fake_time).wait_for_rate_limit(
        reset_epoch=int(fake_time.time()) + 100, retry_after=7.0
    )

    assert fake_time.sleeps == [7.0]


def test_rate_limit_wait_defaults_to_a_minute(fake_time: FakeTime) -> None:
    make_pacer(fake_time).wait_for_rate_limit(reset_epoch=None, retry_after=None)

    assert fake_time.sleeps == [60.0]


def test_rate_limit_wait_over_max_raises(fake_time: FakeTime) -> None:
    reset_epoch = int(fake_time.time()) + 600

    with pytest.raises(GitHubRateLimitError) as caught:
        make_pacer(fake_time).wait_for_rate_limit(reset_epoch=reset_epoch, retry_after=None)

    assert caught.value.reset_at == datetime.fromtimestamp(reset_epoch, tz=UTC)
    assert fake_time.sleeps == []


def test_backoff_doubles_each_attempt(fake_time: FakeTime) -> None:
    pacer = make_pacer(fake_time)

    for attempt in (1, 2, 3):
        pacer.backoff(attempt)

    assert fake_time.sleeps == [2.0, 4.0, 8.0]


def test_min_interval_depends_on_token() -> None:
    assert select_min_interval("ghp_co-token") == 2.1
    assert select_min_interval("") == 6.1


def test_negative_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="âm"):
        CallBudget(-1)


# --- Đồng hồ máy lệch: chờ theo giờ của GitHub (đọc từ header Date), không theo giờ máy ---------


@pytest.mark.parametrize("skew", [600.0, -600.0], ids=["may-nhanh-10-phut", "may-cham-10-phut"])
def test_rate_limit_wait_follows_github_clock_when_local_clock_is_off(
    fake_time: FakeTime, skew: float
) -> None:
    pacer = make_pacer(fake_time)
    github_now = fake_time.time() - skew
    pacer.observe_server_time(github_now)

    pacer.wait_for_rate_limit(reset_epoch=int(github_now) + 30, retry_after=None)

    assert fake_time.sleeps == [pytest.approx(31, abs=1)]


def test_quota_wait_follows_github_clock_when_local_clock_is_off(fake_time: FakeTime) -> None:
    pacer = make_pacer(fake_time)
    github_now = fake_time.time() - 600  # máy nhanh 10 phút
    pacer.before_request()
    pacer.observe_server_time(github_now)
    pacer.record_response(remaining=0, reset_epoch=int(github_now) + 30)

    pacer.before_request()

    assert fake_time.sleeps == [pytest.approx(31, abs=1)]


def test_missing_server_time_keeps_local_clock(fake_time: FakeTime) -> None:
    pacer = make_pacer(fake_time)
    pacer.observe_server_time(None)

    pacer.wait_for_rate_limit(reset_epoch=int(fake_time.time()) + 30, retry_after=None)

    assert fake_time.sleeps == [pytest.approx(31, abs=1)]
