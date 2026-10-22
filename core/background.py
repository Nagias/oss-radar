"""Chạy việc nền: MỘT luồng xử lý chung cho cả app, nằm ngay trong tiến trình web (QĐ-14).

Đây là nơi duy nhất được tạo luồng (ruff chặn `threading`, `concurrent.futures` ở nơi khác).
Một luồng duy nhất → mỗi lúc chỉ một việc ghi CSDL (SQLite chỉ một bên ghi) và hạn mức GitHub
không bị hai việc tranh nhau.
"""

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from django.db import connections

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="oss-radar-nen")


def submit(job: Callable[[int], None], arg: int) -> Future[None]:
    """Xếp `job(arg)` vào luồng nền. Lỗi trong việc được ghi log đầy đủ, không bị nuốt."""
    return _executor.submit(_run, job, arg)


def _run(job: Callable[[int], None], arg: int) -> None:
    try:
        job(arg)
    except Exception:
        logger.exception("Việc nền %s(%s) gặp lỗi", getattr(job, "__name__", job), arg)
        raise
    finally:
        # Mỗi luồng có kết nối CSDL riêng; đóng lại để không rò kết nối sau mỗi việc.
        connections.close_all()
