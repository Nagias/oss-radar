"""`uv run poe dev` (`manage.py runserver`) của dự án: như lệnh gốc, thêm bật bộ nhịp (QĐ-15).

Ghi đè lệnh của `django.contrib.staticfiles` (app `core` đứng trước trong `INSTALLED_APPS`) và kế
thừa nó, nên vẫn phục vụ file tĩnh như cũ.
"""

from typing import Any

from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticfilesRunserver,
)
from django.core.handlers.wsgi import WSGIHandler

from core import scheduler


class Command(StaticfilesRunserver):
    help = "Chạy web để dùng trên máy (máy chủ phát triển), kèm bộ nhịp chạy việc định kỳ."

    def get_handler(self, *args: Any, **options: Any) -> WSGIHandler:
        # Django chỉ gọi get_handler trong inner_run, tức ở tiến trình phục vụ web (tiến trình con
        # của bộ tự khởi động lại, hoặc tiến trình duy nhất khi --noreload), và chỉ SAU khi kiểm
        # tra hệ thống và migration đã qua. Tiến trình theo dõi file không tới đây → không có hai
        # bộ nhịp; cấu hình hỏng thì bộ nhịp không bật.
        handler = super().get_handler(*args, **options)
        scheduler.start()
        return handler
