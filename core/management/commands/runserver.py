"""`uv run poe dev` (`manage.py runserver`) của dự án: như lệnh gốc, thêm bật bộ nhịp (QĐ-15).

Ghi đè lệnh của `django.contrib.staticfiles` (app `core` đứng trước trong `INSTALLED_APPS`) và kế
thừa nó, nên vẫn phục vụ file tĩnh như cũ.
"""

from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticfilesRunserver,
)

from core import scheduler


class Command(StaticfilesRunserver):
    help = "Chạy web để dùng trên máy (máy chủ phát triển), kèm bộ nhịp chạy việc định kỳ."

    def on_bind(self, server_port: int) -> None:
        # Django chỉ gọi on_bind trong inner_run, tức ở tiến trình phục vụ web (tiến trình con của
        # bộ tự khởi động lại, hoặc tiến trình duy nhất khi --noreload), SAU khi kiểm tra hệ thống,
        # migration đã qua và máy chủ đã giữ được cổng. Vì vậy: tiến trình theo dõi file không tới
        # đây (không có hai bộ nhịp); cấu hình hỏng thì bộ nhịp không bật; lỡ mở app lần hai khi
        # cổng đã bận thì bản thứ hai bị tắt trước khi kịp chạy việc định kỳ nào.
        super().on_bind(server_port)
        scheduler.start()
