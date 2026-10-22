"""Bộ nhịp: luồng hẹn giờ nhỏ chạy trong tiến trình phục vụ web (QĐ-15).

Cứ mỗi nhịp (và ngay khi bật), nếu luồng nền rảnh thì đẩy MỘT việc "kiểm tra lịch" vào
`core.background`; đang bận thì bỏ qua nhịp đó, không xếp chồng. Việc kiểm tra chạy trên luồng nền
và gọi lần lượt các việc định kỳ khai trong `settings.SCHEDULED_JOBS`.

Luồng bộ nhịp KHÔNG đụng CSDL: mọi việc đọc/ghi vẫn chỉ ở một luồng nền (QĐ-14). Chỉ lệnh
`runserver` của dự án bật bộ nhịp, nên `migrate`, test và các lệnh khác không tự chạy việc định kỳ.
"""

import logging
import threading

from django.conf import settings
from django.utils.module_loading import import_string

from core import background

logger = logging.getLogger(__name__)

TICK_SECONDS = 300.0
CHECK_LABEL = "Kiểm tra lịch"

_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


def run_scheduled_jobs(_: int = 0) -> None:
    """Gọi lần lượt từng việc định kỳ (trên luồng nền). Lỗi để nổi lên cho luồng nền ghi log."""
    for path in settings.SCHEDULED_JOBS:
        import_string(path)()


def tick() -> bool:
    """Một nhịp: luồng nền rảnh thì đẩy việc kiểm tra lịch và trả `True`; bận thì `False`."""
    if background.busy_label() is not None:
        return False
    background.submit(run_scheduled_jobs, 0, label=CHECK_LABEL)
    return True


def start(*, interval: float = TICK_SECONDS) -> None:
    """Bật luồng bộ nhịp (daemon: tắt app là tắt theo). Đã bật rồi thì không bật thêm."""
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(
            target=_beat_forever, args=(interval,), name="oss-radar-nhip", daemon=True
        )
        _thread.start()
    logger.info("Đã bật bộ nhịp: kiểm tra lịch ngay, rồi cứ %s giây một lần", interval)


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def _beat_forever(interval: float) -> None:
    pause = threading.Event()
    while True:
        tick()
        pause.wait(interval)
