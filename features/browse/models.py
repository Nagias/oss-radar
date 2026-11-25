"""Dữ liệu của trang Khám phá: góc nhìn đã lưu (F-012)."""

from django.db import models
from django.db.models.functions import Lower


class SavedView(models.Model):
    """Một tổ hợp lọc có tên (tab, ô lọc, cách sắp), mở lại bằng một bấm ở thanh bên.

    `query` là chuỗi chuẩn (`filters.canonical_query`): hai bộ lọc giống nhau thì chuỗi giống nhau.
    """

    name = models.CharField("Tên", max_length=60)
    query = models.CharField("Bộ lọc", max_length=1000, blank=True)
    position = models.PositiveIntegerField("Thứ tự", default=0)
    created_at = models.DateTimeField("Tạo lúc", auto_now_add=True)
    updated_at = models.DateTimeField("Sửa lúc", auto_now=True)

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = "góc nhìn"
        verbose_name_plural = "góc nhìn"
        constraints = [
            models.UniqueConstraint(Lower("name"), name="browse_savedview_name_unique_ci"),
        ]

    def __str__(self) -> str:
        return self.name
