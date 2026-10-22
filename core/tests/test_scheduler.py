"""Bộ nhịp: đẩy việc "kiểm tra lịch" vào luồng nền khi rảnh; chỉ bật ở tiến trình phục vụ web."""

import threading
from collections.abc import Iterator
from concurrent.futures import Future
from typing import Any

import pytest
from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticfilesRunserver,
)
from django.core.management import call_command, get_commands
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


def test_tick_skips_when_background_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: list[Any] = []
    monkeypatch.setattr(background, "busy_label", lambda: "Lượt quét hằng ngày 22/10")
    monkeypatch.setattr(background, "submit", lambda *args, **kwargs: submitted.append(args))

    assert scheduler.tick() is False
    assert submitted == []


def test_tick_submits_when_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    futures: list[Future[None]] = []
    real_submit = background.submit

    def spy_submit(job: Any, arg: int, *, label: str = "") -> Future[None]:
        future = real_submit(job, arg, label=label)
        futures.append(future)
        return future

    monkeypatch.setattr(background, "submit", spy_submit)

    with override_settings(SCHEDULED_JOBS=[f"{__name__}.record_busy_label"]):
        assert scheduler.tick() is True
        assert len(futures) == 1
        futures[0].result(timeout=5)

    assert _calls == ["Kiểm tra lịch"]  # việc định kỳ chạy trên luồng nền, dưới nhãn này
    assert background.busy_label() is None


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


def test_runserver_inner_run_starts_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(scheduler, "start", lambda **kwargs: events.append("bật bộ nhịp"))
    monkeypatch.setattr(
        StaticfilesRunserver,
        "inner_run",
        lambda self, *args, **options: events.append("phục vụ web"),
    )

    CoreRunserver().inner_run(None, use_threading=True)

    assert events == ["bật bộ nhịp", "phục vụ web"]


@pytest.mark.django_db
def test_scheduler_not_started_by_setup_or_migrate() -> None:
    before = _beat_threads()

    call_command("migrate", verbosity=0)

    assert scheduler.is_running() is False
    assert _beat_threads() == before
