"""Chạy nền: việc chạy trên luồng riêng, lỗi ghi log không bị nuốt, luồng vẫn sống cho việc sau."""

import logging
import threading

import pytest

from core import background


def test_job_runs_on_background_thread() -> None:
    seen: list[str] = []

    background.submit(
        lambda arg: seen.append(f"{threading.current_thread().name}|{arg}"), 7
    ).result(timeout=5)

    assert len(seen) == 1
    thread_name, arg = seen[0].split("|")
    assert thread_name.startswith("oss-radar-nen")
    assert arg == "7"


def test_failing_job_is_logged_and_next_job_still_runs(caplog: pytest.LogCaptureFixture) -> None:
    def broken(arg: int) -> None:
        raise RuntimeError(f"hỏng giả lập {arg}")

    with caplog.at_level(logging.ERROR, logger="core.background"):
        failed = background.submit(broken, 1)
        with pytest.raises(RuntimeError, match="hỏng giả lập 1"):
            failed.result(timeout=5)

    assert "hỏng giả lập 1" in caplog.text
    done: list[int] = []
    background.submit(done.append, 2).result(timeout=5)
    assert done == [2]


def test_database_connections_closed_after_job(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []
    monkeypatch.setattr("core.background.connections.close_all", lambda: closed.append(True))

    background.submit(lambda arg: None, 1).result(timeout=5)

    assert closed == [True]
