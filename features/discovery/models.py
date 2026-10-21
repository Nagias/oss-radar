from django.db import models

from features.catalog.models import Repository


class ScanRun(models.Model):
    """Một lần quét GitHub theo truy vấn: trạng thái, số liệu, lý do lỗi (nếu có)."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Chờ chạy"
        RUNNING = "running", "Đang quét"
        SUCCEEDED = "succeeded", "Xong"
        FAILED = "failed", "Lỗi"

    query = models.CharField("Truy vấn", max_length=256)
    status = models.CharField(
        "Trạng thái", max_length=20, choices=Status.choices, default=Status.QUEUED
    )
    created_at = models.DateTimeField("Tạo lúc", auto_now_add=True)
    started_at = models.DateTimeField("Bắt đầu", null=True, blank=True)
    finished_at = models.DateTimeField("Kết thúc", null=True, blank=True)
    total_count = models.PositiveIntegerField("Tổng GitHub báo", null=True, blank=True)
    fetched_count = models.PositiveIntegerField("Đã lấy về", default=0)
    created_count = models.PositiveIntegerField("Repo mới", default=0)
    updated_count = models.PositiveIntegerField("Repo đã có", default=0)
    error_message = models.TextField("Lý do lỗi", blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "lần quét"
        verbose_name_plural = "lần quét"

    def __str__(self) -> str:
        return f"#{self.pk} {self.query}"

    @property
    def has_more_on_github(self) -> bool:
        """GitHub báo nhiều kết quả hơn số đã lấy về (xem nợ D-004)."""
        return self.total_count is not None and self.total_count > self.fetched_count


class ScanResult(models.Model):
    """Một repo xuất hiện trong một lần quét. `is_new` = lần quét này mới thấy repo lần đầu."""

    scan_run = models.ForeignKey(ScanRun, on_delete=models.CASCADE, related_name="results")
    repository = models.ForeignKey(
        Repository, on_delete=models.CASCADE, related_name="scan_results"
    )
    is_new = models.BooleanField("Mới thấy lần đầu")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scan_run", "repository"], name="discovery_unique_repo_per_scan"
            )
        ]
        verbose_name = "kết quả quét"
        verbose_name_plural = "kết quả quét"

    def __str__(self) -> str:
        return f"{self.scan_run} → {self.repository}"
