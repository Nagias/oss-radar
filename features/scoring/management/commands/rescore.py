"""Lệnh `manage.py rescore`: tính lại điểm lưu sẵn cho cả kho (sau khi đổi công thức ở rules.py)."""

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import formats

from features.scoring import services


class Command(BaseCommand):
    help = "Tính lại điểm Chất lượng và nghi star giả lưu sẵn cho mọi repo trong kho."

    def handle(self, *args: Any, **options: Any) -> None:
        written = services.refresh_scores()
        count = formats.number_format(written, force_grouping=True)
        self.stdout.write(f"Đã tính lại điểm cho {count} repo.")
