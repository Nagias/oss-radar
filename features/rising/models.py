from django.db import models

from features.catalog.models import Repository
from features.discovery.models import ScanRun


class WatchQuery(models.Model):
    """Một truy vấn trong danh sách theo dõi: mỗi ngày được quét lại bằng một lần quét sâu."""

    label = models.CharField("Mảng", max_length=60)
    query = models.CharField("Truy vấn", max_length=256)
    min_stars = models.PositiveIntegerField("Star tối thiểu", default=10)
    max_stars = models.PositiveIntegerField("Star tối đa", null=True, blank=True)
    budget = models.PositiveIntegerField("Mức quét (lượt gọi)", default=300)
    enabled = models.BooleanField("Đang bật", default=True)
    position = models.PositiveIntegerField("Thứ tự", default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "truy vấn theo dõi"
        verbose_name_plural = "danh sách theo dõi"

    def __str__(self) -> str:
        return f"{self.label}: {self.query}"


class DailyRun(models.Model):
    """Lượt hằng ngày: mỗi ngày (giờ Việt Nam) tối đa một lượt, 5 bước, lưu tiến độ để làm tiếp."""

    class Status(models.TextChoices):
        RUNNING = "running", "Đang quét"
        PAUSED = "paused", "Tạm dừng"
        SUCCEEDED = "succeeded", "Xong"
        SUCCEEDED_PARTIAL = "succeeded_partial", "Xong nhưng còn sót"
        FAILED = "failed", "Lỗi"

    class Step(models.IntegerChoices):
        """Thứ tự chạy: quét lại → lọc thô → xác minh → lấy hồ sơ chủ → lập báo cáo.

        `OWNERS` mang số 5 dù chạy trước `REPORT`: lượt cũ đã lập báo cáo lưu `step=4`. Code chỉ so
        bằng, không so lớn nhỏ giữa các bước.
        """

        RESCAN = 1, "Quét lại danh sách theo dõi"
        SCREEN = 2, "Lọc thô"
        VERIFY = 3, "Xác minh"
        REPORT = 4, "Lập báo cáo"
        OWNERS = 5, "Lấy hồ sơ chủ repo"

    class PauseKind(models.TextChoices):
        STOPPED = "stopped", "Người dùng bấm Dừng"
        INTERRUPTED = "interrupted", "Bị gián đoạn"
        RETRY_LATER = "retry_later", "Chờ GitHub hoặc mạng"

    day = models.DateField("Ngày", unique=True)
    status = models.CharField(
        "Trạng thái", max_length=20, choices=Status.choices, default=Status.RUNNING
    )
    step = models.PositiveSmallIntegerField(
        "Bước đang làm", choices=Step.choices, default=Step.RESCAN
    )
    pause_kind = models.CharField(
        "Kiểu tạm dừng", max_length=12, choices=PauseKind.choices, blank=True, default=""
    )
    started_at = models.DateTimeField("Bắt đầu", null=True, blank=True)
    finished_at = models.DateTimeField("Kết thúc", null=True, blank=True)
    heartbeat_at = models.DateTimeField("Nhịp sống gần nhất", null=True, blank=True)
    paused_at = models.DateTimeField("Tạm dừng lúc", null=True, blank=True)
    runner_token = models.CharField(
        "Mã lượt chạy đang giữ lượt", max_length=32, blank=True, default=""
    )
    stop_requested = models.BooleanField("Người dùng bấm Dừng", default=False)
    stop_reason = models.TextField("Lý do dừng hoặc còn sót", blank=True, default="")
    error_message = models.TextField("Lý do lỗi", blank=True, default="")
    problems = models.JSONField("Các chỗ còn sót", default=list, blank=True)
    auto_continue_count = models.PositiveSmallIntegerField("Số lần tự chạy tiếp", default=0)
    last_auto_continue_at = models.DateTimeField("Tự chạy tiếp gần nhất", null=True, blank=True)
    search_calls_used = models.PositiveIntegerField("Lượt gọi Search đã dùng", default=0)
    verify_budget = models.PositiveIntegerField("Ngân sách xác minh", default=0)
    verify_calls_used = models.PositiveIntegerField("Lượt gọi xác minh đã dùng", default=0)
    owner_budget = models.PositiveIntegerField("Ngân sách hồ sơ chủ repo", default=0)
    owner_calls_used = models.PositiveIntegerField("Lượt gọi hồ sơ chủ đã dùng", default=0)
    candidate_count = models.PositiveIntegerField("Số ứng viên", default=0)
    unverified_count = models.PositiveIntegerField("Ứng viên chưa xác minh", default=0)
    insufficient_count = models.PositiveIntegerField("Chưa đủ dữ liệu", default=0)
    rising_count = models.PositiveIntegerField("Số rising star", default=0)
    new_repo_count = models.PositiveIntegerField("Repo mới phát hiện", default=0)
    window_end = models.DateField("Ngày UTC cuối của cửa sổ tính tăng", null=True, blank=True)

    class Meta:
        ordering = ["-day"]
        verbose_name = "lượt quét hằng ngày"
        verbose_name_plural = "lượt quét hằng ngày"

    def __str__(self) -> str:
        return f"Lượt {self.day:%d/%m/%Y} ({self.get_status_display()})"


class DailyRunScan(models.Model):
    """Lần quét của một truy vấn theo dõi trong một lượt hằng ngày.

    Truy vấn bị xoá giữa chừng thì liên kết tới lần quét vẫn còn (`watch_query` thành trống). Một
    truy vấn có thể có hai lần quét trong cùng lượt: lần đầu lỗi token / lỗi code, chạy tiếp thì
    quét lại bằng lần mới (`position` lớn hơn).
    """

    daily_run = models.ForeignKey(DailyRun, on_delete=models.CASCADE, related_name="scans")
    watch_query = models.ForeignKey(
        WatchQuery,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_scans",
    )
    scan_run = models.OneToOneField(ScanRun, on_delete=models.CASCADE, related_name="daily_scan")
    position = models.PositiveIntegerField("Thứ tự trong lượt")

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["daily_run", "scan_run"], name="rising_unique_scan_per_run"
            )
        ]
        verbose_name = "lần quét của lượt hằng ngày"
        verbose_name_plural = "lần quét của lượt hằng ngày"

    def __str__(self) -> str:
        return f"{self.daily_run} → {self.scan_run}"


class RisingCheck(models.Model):
    """Một repo được xét trong một lượt: số tăng, nguồn số liệu, có là rising star, cờ cảnh giác."""

    class Source(models.TextChoices):
        HISTORY = "history", "Lịch sử star GitHub"
        SNAPSHOT = "snapshot", "Ước lượng từ ảnh chụp"
        AGE = "age", "Ước lượng theo tuổi repo"

    daily_run = models.ForeignKey(DailyRun, on_delete=models.CASCADE, related_name="checks")
    repository = models.ForeignKey(
        Repository, on_delete=models.CASCADE, related_name="rising_checks"
    )
    stars = models.PositiveIntegerField("Star lúc xét")
    source = models.CharField("Nguồn số liệu", max_length=10, choices=Source.choices)
    gain_1d = models.IntegerField("Tăng 1 ngày", null=True, blank=True)
    gain_7d = models.IntegerField("Tăng 7 ngày")
    gain_30d = models.IntegerField("Tăng 30 ngày", null=True, blank=True)
    series = models.JSONField("Star mới từng ngày (30 ngày)", default=list, blank=True)
    window_end = models.DateField("Ngày UTC cuối của cửa sổ", null=True, blank=True)
    baseline_day = models.DateField("Ngày của ảnh chụp mốc", null=True, blank=True)
    is_rising = models.BooleanField("Là rising star", default=False)
    flags = models.JSONField("Cờ cảnh giác", default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["daily_run", "repository"], name="rising_unique_check_per_repo"
            )
        ]
        verbose_name = "kết quả xét rising"
        verbose_name_plural = "kết quả xét rising"

    def __str__(self) -> str:
        return f"{self.daily_run} · {self.repository}"
