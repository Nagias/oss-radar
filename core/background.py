"""Chạy việc nền: MỘT luồng xử lý chung cho cả app, nằm ngay trong tiến trình web (QĐ-14).

Đây là nơi duy nhất được tạo luồng xử lý việc (ruff chặn `threading`, `concurrent.futures` ở nơi
khác; riêng `core/scheduler.py` được tạo luồng hẹn giờ, không đụng CSDL). Một luồng duy nhất → mỗi
lúc chỉ một việc ghi CSDL (SQLite chỉ một bên ghi) và hạn mức GitHub không bị hai việc tranh nhau.

Luồng là luồng "daemon": tắt app thì nó chết theo ngay, không bắt app chờ việc đang dở. Việc dở
không mất: nó được nhận ra là "bị gián đoạn" (nhịp sống cũ) và bấm Tiếp tục để chạy nốt.

Mỗi việc có một nhãn (vd "Lượt quét hằng ngày 22/10") để trang web cho biết luồng nền đang bận
việc gì.
"""

import logging
import queue
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future

from django.db import connections

logger = logging.getLogger(__name__)

DEFAULT_LABEL = "việc nền"

_Job = tuple[Callable[[int], None], int, "Future[None]"]
_jobs: queue.Queue[_Job] = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()

# Nhãn được đọc từ luồng phục vụ web trong lúc luồng nền đổi nó → luôn đọc/ghi dưới khoá.
# `_queued_labels` đi đúng thứ tự với `_jobs`: cả hai được thêm vào trong cùng một lần giữ khoá.
_state_lock = threading.Lock()
_queued_labels: deque[str] = deque()
_running_label: str | None = None


def submit(job: Callable[[int], None], arg: int, *, label: str = "") -> Future[None]:
    """Xếp `job(arg)` vào luồng nền. Lỗi được ghi log và giữ trong Future, không bị nuốt."""
    future: Future[None] = Future()
    with _state_lock:
        _queued_labels.append(label or DEFAULT_LABEL)
        _jobs.put((job, arg, future))
    _ensure_worker()
    return future


def busy_label() -> str | None:
    """Nhãn việc đang chạy, hoặc việc đầu hàng chờ nếu chưa chạy; rảnh hẳn thì `None`."""
    with _state_lock:
        if _running_label is not None:
            return _running_label
        return _queued_labels[0] if _queued_labels else None


def relabel(label: str) -> None:
    """Việc đang chạy trên luồng nền tự đổi nhãn của mình.

    Gọi từ luồng khác (hàm việc gọi thẳng trong test hay lệnh dòng lệnh) thì không có việc nền nào
    của nó để đổi tên → bỏ qua, để luồng nền không bị báo "bận" giả mãi.
    """
    if threading.current_thread() is _worker:
        _set_running(label)


def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work_forever, name="oss-radar-nen", daemon=True)
            _worker.start()


def _work_forever() -> None:
    while True:
        job, arg, future = _jobs.get()
        _promote_queued_label()
        if not future.set_running_or_notify_cancel():
            _set_running(None)
            continue
        error = _run(job, arg)
        # Báo Future xong SAU khi đã dọn kết nối và về trạng thái rảnh: ai chờ Future sẽ thấy
        # `busy_label()` đúng ngay.
        if error is None:
            future.set_result(None)
        else:
            future.set_exception(error)


def _run(job: Callable[[int], None], arg: int) -> Exception | None:
    try:
        job(arg)
    except Exception as exc:
        logger.exception("Việc nền %s(%s) gặp lỗi", getattr(job, "__name__", job), arg)
        return exc
    finally:
        # Mỗi luồng có kết nối CSDL riêng; đóng lại để không rò kết nối sau mỗi việc.
        connections.close_all()
        _set_running(None)
    return None


def _promote_queued_label() -> None:
    # Lấy khỏi hàng chờ và đặt là "đang chạy" trong cùng một lần giữ khoá: không có khoảnh khắc
    # nào `busy_label()` báo rảnh trong khi việc sắp chạy.
    global _running_label
    with _state_lock:
        _running_label = _queued_labels.popleft()


def _set_running(label: str | None) -> None:
    global _running_label
    with _state_lock:
        _running_label = label
