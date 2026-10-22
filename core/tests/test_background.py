"""Chạy nền: việc chạy trên luồng riêng, lỗi ghi log không bị nuốt, luồng vẫn sống cho việc sau."""

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

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


_EXIT_PROBE = """
import os, sys, time
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from core import background
background.submit(lambda seconds: time.sleep(seconds), 30)
time.sleep(0.5)
"""


def test_process_exits_promptly_while_a_long_job_runs() -> None:
    # Tắt app giữa lúc đang quét: phải thoát ngay (lần quét thành "bị gián đoạn", bấm Tiếp tục
    # sau) chứ không treo tới khi việc nền chạy xong.
    started = time.monotonic()

    result = subprocess.run(  # noqa: S603 — chạy chính trình thông dịch của dự án
        [sys.executable, "-c", _EXIT_PROBE],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        timeout=25,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert time.monotonic() - started < 15


def test_cancelled_job_is_skipped_and_worker_moves_on() -> None:
    gate = threading.Event()
    ran: list[int] = []
    blocker = background.submit(lambda arg: gate.wait(5), 0)
    waiting = background.submit(ran.append, 1)

    assert waiting.cancel()  # huỷ khi còn đang xếp hàng
    gate.set()
    blocker.result(timeout=5)
    background.submit(ran.append, 2).result(timeout=5)

    assert ran == [2]
