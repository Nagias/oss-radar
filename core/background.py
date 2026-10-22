"""Chạy việc nền: MỘT luồng xử lý chung cho cả app, nằm ngay trong tiến trình web (QĐ-14).

Đây là nơi duy nhất được tạo luồng (ruff chặn `threading`, `concurrent.futures` ở nơi khác).
Một luồng duy nhất → mỗi lúc chỉ một việc ghi CSDL (SQLite chỉ một bên ghi) và hạn mức GitHub
không bị hai việc tranh nhau.

Luồng là luồng "daemon": tắt app thì nó chết theo ngay, không bắt app chờ việc đang dở. Việc dở
không mất: nó được nhận ra là "bị gián đoạn" (nhịp sống cũ) và bấm Tiếp tục để chạy nốt.
"""

import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future

from django.db import connections

logger = logging.getLogger(__name__)

_Job = tuple[Callable[[int], None], int, "Future[None]"]
_jobs: queue.Queue[_Job] = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def submit(job: Callable[[int], None], arg: int) -> Future[None]:
    """Xếp `job(arg)` vào luồng nền. Lỗi được ghi log và giữ trong Future, không bị nuốt."""
    future: Future[None] = Future()
    _jobs.put((job, arg, future))
    _ensure_worker()
    return future


def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work_forever, name="oss-radar-nen", daemon=True)
            _worker.start()


def _work_forever() -> None:
    while True:
        job, arg, future = _jobs.get()
        if not future.set_running_or_notify_cancel():
            continue
        try:
            job(arg)
        except Exception as exc:
            logger.exception("Việc nền %s(%s) gặp lỗi", getattr(job, "__name__", job), arg)
            future.set_exception(exc)
        else:
            future.set_result(None)
        finally:
            # Mỗi luồng có kết nối CSDL riêng; đóng lại để không rò kết nối sau mỗi việc.
            connections.close_all()
