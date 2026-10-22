"""Bộ nhịp: đẩy việc "kiểm tra lịch" vào luồng nền khi rảnh; chỉ bật ở tiến trình phục vụ web."""

import logging
import threading
from collections.abc import Iterator
from concurrent.futures import Future
from typing import Any

import pytest
from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticfilesRunserver,
)
from django.core.management import call_command, get_commands
from django.core.management.base import SystemCheckError
from django.test import override_settings

from core import background, scheduler
from core.management.commands.runserver import Command as CoreRunserver

_calls: list[str] = []


def first_job() -> None:
    _calls.append("first")


def second_job() -> None:
    _calls.append("second")


def broken_job() -> None:
    raise RuntimeError("việc định kỳ hỏng giả lập")


def record_busy_label() -> None:
    _calls.append(str(background.busy_label()))


@pytest.fixture(autouse=True)
def _reset_calls() -> Iterator[None]:
    _calls.clear()
    yield
    _calls.clear()


def _beat_threads() -> set[threading.Thread]:
    return {t for t in threading.enumerate() if t.name == "oss-radar-nhip"}


def test_run_scheduled_jobs_calls_each_path_in_order() -> None:
    with override_settings(SCHEDULED_JOBS=[f"{__name__}.second_job", f"{__name__}.first_job"]):
        scheduler.run_scheduled_jobs()

    assert _calls == ["second", "first"]


def test_run_scheduled_jobs_lets_errors_propagate() -> None:
    jobs = [f"{__name__}.broken_job", f"{__name__}.first_job"]
    with override_settings(SCHEDULED_JOBS=jobs), pytest.raises(RuntimeError, match="hỏng"):
        scheduler.run_scheduled_jobs()

    assert _calls == []


def test_tick_skips_when_background_busy() -> None:
    started, release = threading.Event(), threading.Event()

    def hold(_: int) -> None:
        started.set()
        release.wait(5)

    with override_settings(SCHEDULED_JOBS=[f"{__name__}.first_job"]):
        holder = background.submit(hold, 0, label="Lượt quét hằng ngày 22/10")
        try:
            assert started.wait(5)
            assert scheduler.tick() is False
        finally:
            release.set()
        holder.result(timeout=5)
        # Hàng chờ chạy theo thứ tự: việc mốc này xong thì việc kiểm tra (nếu đã xếp) cũng đã chạy.
        background.submit(lambda arg: None, 0).result(timeout=5)

    assert _calls == []


def test_tick_submits_when_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    futures: list[Future[None] | None] = []
    real_submit_if_idle = background.submit_if_idle

    def spy_submit_if_idle(job: Any, arg: int, *, label: str = "") -> Future[None] | None:
        future = real_submit_if_idle(job, arg, label=label)
        futures.append(future)
        return future

    monkeypatch.setattr(background, "submit_if_idle", spy_submit_if_idle)

    with override_settings(SCHEDULED_JOBS=[f"{__name__}.record_busy_label"]):
        assert scheduler.tick() is True
        assert len(futures) == 1
        submitted = futures[0]
        assert submitted is not None
        submitted.result(timeout=5)

    assert _calls == ["Kiểm tra lịch"]  # việc định kỳ chạy trên luồng nền, dưới nhãn này
    assert background.busy_label() is None


def test_beat_loop_logs_and_reraises_when_tick_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken_tick() -> bool:
        raise RuntimeError("nhịp hỏng giả lập")

    monkeypatch.setattr(scheduler, "tick", broken_tick)

    with (
        caplog.at_level(logging.ERROR, logger="core.scheduler"),
        pytest.raises(RuntimeError, match="nhịp hỏng giả lập"),
    ):
        scheduler._beat_forever(3600)

    assert "nhịp hỏng giả lập" in caplog.text


def test_start_is_idempotent_and_thread_is_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    ticked = threading.Event()
    # Không đẩy việc thật vào luồng nền; khoảng nghỉ rất dài nên sau test luồng không gọi lại.
    monkeypatch.setattr(scheduler, "tick", ticked.set)
    monkeypatch.setattr(scheduler, "_thread", None)
    before = _beat_threads()

    scheduler.start(interval=3600)
    scheduler.start(interval=3600)

    assert ticked.wait(5)  # gọi tick() ngay khi bật, không chờ hết khoảng nghỉ
    started = _beat_threads() - before
    assert len(started) == 1
    assert started.pop().daemon
    assert scheduler.is_running()


def test_runserver_command_comes_from_core() -> None:
    assert get_commands()["runserver"] == "core"


def test_runserver_get_handler_starts_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    handler = object()

    def staticfiles_get_handler(self: StaticfilesRunserver, *args: Any, **options: Any) -> Any:
        events.append("dựng handler phục vụ web và file tĩnh")
        return handler

    monkeypatch.setattr(scheduler, "start", lambda **kwargs: events.append("bật bộ nhịp"))
    monkeypatch.setattr(StaticfilesRunserver, "get_handler", staticfiles_get_handler)

    assert CoreRunserver().get_handler() is handler
    assert events == ["dựng handler phục vụ web và file tĩnh", "bật bộ nhịp"]


def test_runserver_does_not_start_scheduler_when_system_checks_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[bool] = []
    monkeypatch.setattr(scheduler, "start", lambda **kwargs: started.append(True))
    command = CoreRunserver()

    def failing_check(**kwargs: Any) -> None:
        raise SystemCheckError("cấu hình hỏng giả lập")

    monkeypatch.setattr(command, "check", failing_check)

    with pytest.raises(SystemCheckError, match="cấu hình hỏng"):
        command.inner_run(None, use_threading=True, skip_checks=False)

    assert started == []


@pytest.mark.django_db
def test_scheduler_not_started_by_setup_or_migrate() -> None:
    before = _beat_threads()

    call_command("migrate", verbosity=0)

    assert scheduler.is_running() is False
    assert _beat_threads() == before
