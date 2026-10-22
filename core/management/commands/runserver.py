"""`uv run poe dev` (`manage.py runserver`) của dự án: như lệnh gốc, thêm bật bộ nhịp (QĐ-15).

Ghi đè lệnh của `django.contrib.staticfiles` (app `core` đứng trước trong `INSTALLED_APPS`) và kế
thừa nó, nên vẫn phục vụ file tĩnh như cũ.
"""

from typing import Any

from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticfilesRunserver,
)

from core import scheduler


class Command(StaticfilesRunserver):
    help = "Chạy web để dùng trên máy (máy chủ phát triển), kèm bộ nhịp chạy việc định kỳ."

    def inner_run(self, *args: Any, **options: Any) -> None:
        # Django chỉ gọi inner_run ở tiến trình phục vụ web: tiến trình con của bộ tự khởi động
        # lại, hoặc tiến trình duy nhất khi --noreload. Tiến trình theo dõi file không gọi tới đây,
        # nên không có hai bộ nhịp cùng đẩy việc.
        scheduler.start()
        super().inner_run(*args, **options)
