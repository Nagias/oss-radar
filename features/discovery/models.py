import math
from datetime import timedelta

from django.db import models
from django.utils import timezone

from features.catalog.models import Repository
from features.discovery.slicing import SliceRange

# Lần quét "đang chạy thật" nếu nhịp sống mới hơn khoảng này (luồng quét ghi mỗi ≤ 30 giây).
LIVE_HEARTBEAT_WINDOW = timedelta(seconds=120)


class ScanRun(models.Model):
    """Một lần quét GitHub: truy vấn, phạm vi, ngân sách, trạng thái, số liệu, lý do dừng/lỗi."""

    class Status(models.TextChoices):
        RUNNING = "running", "Đang quét"
        PAUSED = "paused", "Tạm dừng"
        SUCCEEDED = "succeeded", "Xong"
        SUCCEEDED_PARTIAL = "succeeded_partial", "Xong nhưng còn sót"
        FAILED = "failed", "Lỗi"

    class Origin(models.TextChoices):
        MANUAL = "manual", "Quét tay"
        DAILY = "daily", "Hằng ngày"

    class ErrorKind(models.TextChoices):
        QUERY = "query", "Truy vấn sai"
        AUTH = "auth", "Token sai"
        UNEXPECTED = "unexpected", "Lỗi bất ngờ"

    query = models.CharField("Truy vấn", max_length=256)
    origin = models.CharField(
        "Nguồn chạy", max_length=10, choices=Origin.choices, default=Origin.MANUAL
    )
    min_stars = models.PositiveIntegerField("Star tối thiểu", default=0)
    max_stars = models.PositiveIntegerField("Star tối đa", null=True, blank=True)
    created_from = models.DateField("Tạo từ ngày", null=True, blank=True)
    created_to = models.DateField("Tạo đến ngày", null=True, blank=True)
    budget = models.PositiveIntegerField("Ngân sách lượt gọi", default=1)
    api_calls_used = models.PositiveIntegerField("Lượt gọi đã dùng", default=0)
    status = models.CharField(
        "Trạng thái", max_length=20, choices=Status.choices, default=Status.RUNNING
    )
    created_at = models.DateTimeField("Tạo lúc", auto_now_add=True)
    started_at = models.DateTimeField("Bắt đầu", null=True, blank=True)
    finished_at = models.DateTimeField("Kết thúc", null=True, blank=True)
    heartbeat_at = models.DateTimeField("Nhịp sống gần nhất", null=True, blank=True)
    waiting_until = models.DateTimeField("Đang chờ GitHub tới", null=True, blank=True)
    stop_requested = models.BooleanField("Người dùng bấm Dừng", default=False)
    runner_token = models.CharField(
        "Mã lượt chạy đang giữ lần quét", max_length=32, blank=True, default=""
    )
    stop_reason = models.TextField("Lý do dừng hoặc còn sót", blank=True, default="")
    total_count = models.PositiveIntegerField("Tổng GitHub báo", null=True, blank=True)
    fetched_count = models.PositiveIntegerField("Đã lấy về", default=0)
    created_count = models.PositiveIntegerField("Repo mới", default=0)
    updated_count = models.PositiveIntegerField("Repo đã có", default=0)
    error_message = models.TextField("Lý do lỗi", blank=True, default="")
    error_kind = models.CharField(
        "Loại lỗi", max_length=12, blank=True, default="", choices=ErrorKind.choices
    )
    auto_resume_count = models.PositiveSmallIntegerField("Số lần tự chạy tiếp", default=0)
    last_auto_resume_at = models.DateTimeField("Tự chạy tiếp gần nhất", null=True, blank=True)
    results_pruned = models.BooleanField("Đã dọn danh sách repo", default=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "lần quét"
        verbose_name_plural = "lần quét"

    def __str__(self) -> str:
        return f"#{self.pk} {self.query}"

    @property
    def is_live(self) -> bool:
        """Đang chạy thật ở đâu đó (trang web hoặc lệnh dòng lệnh), không phải bị bỏ dở."""
        if self.status != self.Status.RUNNING or self.heartbeat_at is None:
            return False
        return self.heartbeat_at >= timezone.now() - LIVE_HEARTBEAT_WINDOW

    @property
    def can_resume(self) -> bool:
        return self.status in (self.Status.PAUSED, self.Status.SUCCEEDED_PARTIAL)

    @property
    def coverage_percent(self) -> float | None:
        """Độ phủ = đã lấy / GitHub báo. GitHub báo 0 kết quả thì coi là đủ 100%."""
        if self.total_count is None:
            return None
        if self.total_count == 0:
            return 100.0
        # Làm tròn XUỐNG: thiếu dù 1 repo cũng không được hiện "100%".
        return min(100.0, math.floor(self.fetched_count * 1000 / self.total_count) / 10)


class ScanSlice(models.Model):
    """Một lát của lần quét: truy vấn gốc giới hạn trong một khoảng ngày tạo và khoảng star.

    Lát kế tiếp được làm là lát `pending` có `stack_order` lớn nhất → làm theo chiều sâu, mới trước.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Chưa làm"
        DONE = "done", "Xong"
        SPLIT = "split", "Đã chia nhỏ"
        TRUNCATED = "truncated", "Bị cắt (quá 1.000 kết quả)"
        INCOMPLETE = "incomplete", "Chưa chắc đủ"
        FAILED = "failed", "Lỗi"

    scan_run = models.ForeignKey(ScanRun, on_delete=models.CASCADE, related_name="slices")
    stack_order = models.PositiveIntegerField("Thứ tự")
    created_from = models.DateField("Tạo từ ngày")
    created_to = models.DateField("Tạo đến ngày")
    stars_min = models.PositiveIntegerField("Star từ")
    stars_max = models.PositiveIntegerField("Star đến", null=True, blank=True)
    status = models.CharField(
        "Trạng thái", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    total_count = models.PositiveIntegerField("GitHub báo", null=True, blank=True)
    pages_fetched = models.PositiveIntegerField("Số trang đã lấy", default=0)
    fetched_count = models.PositiveIntegerField("Số repo đã lấy", default=0)
    retried_incomplete = models.BooleanField("Đã làm lại vì chưa đủ", default=False)
    error_message = models.TextField("Ghi chú lỗi", blank=True, default="")

    class Meta:
        ordering = ["-stack_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["scan_run", "stack_order"], name="discovery_unique_slice_order"
            )
        ]
        verbose_name = "lát quét"
        verbose_name_plural = "lát quét"

    def __str__(self) -> str:
        stars_to = "∞" if self.stars_max is None else str(self.stars_max)
        return (
            f"{self.scan_run} · ngày {self.created_from}..{self.created_to}"
            f" · star {self.stars_min}..{stars_to}"
        )

    @property
    def range(self) -> SliceRange:
        return SliceRange(self.created_from, self.created_to, self.stars_min, self.stars_max)


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
