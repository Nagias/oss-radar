"""Lệnh `manage.py daily`: chạy đúng lượt hôm nay ở tiền cảnh, để chạy tay và để agent tự kiểm."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from pytest_django.fixtures import Settings

from features.discovery.models import ScanRun
from features.rising.models import DailyRun, WatchQuery
from features.rising.tests.conftest import (
    WATCHED,
    FakeGitHub,
    UseFake,
    history,
    item,
    make_run,
    snapshot,
)

pytestmark = pytest.mark.django_db

RISER, STEADY = 301, 302
_, B, _ = WATCHED


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github


@pytest.fixture
def world(watch_list: list[WatchQuery], use_fake: UseFake, settings: Settings) -> FakeGitHub:
    """GitHub giả: RISER có ảnh chụp cũ (tăng 60) và lịch sử +10 mỗi ngày; STEADY chỉ tăng 1."""
    settings.GITHUB_TOKEN = "test-token"
    snapshot(RISER, stars=100)
    snapshot(STEADY, stars=300)
    return use_fake(
        [item(RISER, stars=160), item(STEADY, stars=301)],
        {RISER: history(dict.fromkeys(range(30), 10))},
    )


def press_stop(_: str) -> None:
    """Người dùng bấm Dừng ngay khi lần quét đầu tiên gọi GitHub."""
    DailyRun.objects.update(stop_requested=True)


def run_command() -> str:
    out = StringIO()
    call_command("daily", stdout=out)
    return out.getvalue()


def test_daily_command_runs_and_prints_summary(world: FakeGitHub) -> None:
    text = run_command()

    run = DailyRun.objects.get()
    assert run.status == DailyRun.Status.SUCCEEDED
    assert f"Lượt hằng ngày {timezone.localdate():%d/%m/%Y} — Xong." in text
    assert f"Lượt gọi: Search {run.search_calls_used}, xác minh 1/300." in text
    assert "Rising star: 1" in text
    assert "+70 sao/7 ngày  gia-lap/repo-301 (160 sao)" in text
    assert world.history.requested == [RISER]  # STEADY tăng 1 star: không đáng một lượt gọi


def test_daily_command_prints_notes_when_some_query_is_left_behind(world: FakeGitHub) -> None:
    world.search.fail_when = lambda sent: 422 if sent.startswith(f"{B} ") else None

    text = run_command()

    assert DailyRun.objects.get().status == DailyRun.Status.SUCCEEDED_PARTIAL
    assert "Xong nhưng còn sót." in text
    assert f"Ghi chú: Truy vấn «{B}»" in text
    assert "gia-lap/repo-301" in text  # các truy vấn còn lại vẫn cho kết quả


def test_daily_command_stopped_run_is_reported_not_an_error(world: FakeGitHub) -> None:
    world.search.on_query = press_stop

    text = run_command()

    run = DailyRun.objects.get()
    assert run.status == DailyRun.Status.PAUSED
    assert "Tạm dừng." in text
    assert "Ghi chú: Bạn đã bấm Dừng" in text
    assert "chạy lại `manage.py daily`" in text  # nói rõ cách làm tiếp
    assert "Rising star" not in text  # chưa có báo cáo để in


def test_daily_command_continues_a_paused_run(world: FakeGitHub) -> None:
    world.search.on_query = press_stop
    run_command()
    world.search.on_query = None

    text = run_command()

    assert DailyRun.objects.get().status == DailyRun.Status.SUCCEEDED
    assert DailyRun.objects.count() == 1
    assert "Rising star: 1" in text


def test_daily_command_refuses_when_done(watch_list: list[WatchQuery]) -> None:
    make_run(timezone.localdate())

    with pytest.raises(CommandError, match="Hôm nay đã quét xong"):
        run_command()


def test_daily_command_refuses_while_a_scan_is_live(watch_list: list[WatchQuery]) -> None:
    ScanRun.objects.create(
        query="topic:x", status=ScanRun.Status.RUNNING, heartbeat_at=timezone.now()
    )

    with pytest.raises(CommandError, match="lần quét"):
        run_command()

    assert DailyRun.objects.count() == 0


def test_daily_command_fails_when_the_run_fails(world: FakeGitHub) -> None:
    world.search.fail_when = lambda sent: 401

    with pytest.raises(CommandError, match="GITHUB_TOKEN"):
        run_command()

    assert DailyRun.objects.get().status == DailyRun.Status.FAILED
