from django.db import models

from features.catalog.models import Repository


class RepoClassification(models.Model):
    """Lần phân loại gần nhất của một repo: lý do, model, phiên bản — để kiểm lại và gọi lại.

    `fingerprint` là dấu vân tay của đầu vào (mô tả, topics, ngôn ngữ): đổi thì phân loại lại.
    """

    repository = models.OneToOneField(
        Repository, on_delete=models.CASCADE, related_name="classification"
    )
    reason = models.CharField("Từ khoá khiến AI xếp như vậy", max_length=200, blank=True)
    model = models.CharField("Model AI", max_length=100)
    prompt_version = models.PositiveSmallIntegerField("Phiên bản prompt")
    taxonomy_version = models.PositiveSmallIntegerField("Phiên bản bộ nhóm")
    fingerprint = models.CharField("Dấu vân tay đầu vào", max_length=64)
    classified_at = models.DateTimeField("Phân loại lúc")

    class Meta:
        verbose_name = "phân loại repo"
        verbose_name_plural = "phân loại repo"

    def __str__(self) -> str:
        return str(self.repository)


class RepoLabel(models.Model):
    """Một nhãn của một repo (mỗi nhãn một dòng: lọc HOẶC trong lớp, VÀ giữa hai lớp bằng CSDL)."""

    class Axis(models.TextChoices):
        AUDIENCE = "audience", "Dành cho ai"
        ASPECTS = "aspects", "Làm được gì"

    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name="labels")
    axis = models.CharField("Lớp", max_length=10, choices=Axis.choices)
    code = models.CharField("Mã nhóm", max_length=40)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "axis", "code"], name="taxonomy_unique_label"
            )
        ]
        indexes = [models.Index(fields=["axis", "code"], name="taxonomy_label_code_idx")]
        verbose_name = "nhãn repo"
        verbose_name_plural = "nhãn repo"

    def __str__(self) -> str:
        return f"{self.repository_id}: {self.axis}={self.code}"


class ClassifyRun(models.Model):
    """Một lần phân loại (trong lượt hằng ngày, việc nền phân loại dần, hoặc lệnh `classify`).

    Ghi số lượt gọi và token đã tiêu (nguyên tắc 3). `heartbeat_at` cho biết lần đó còn sống: hai
    lần phân loại không được chạy cùng lúc (gọi trùng, tốn gấp đôi).
    """

    class Origin(models.TextChoices):
        DAILY = "daily", "Lượt hằng ngày"
        BACKLOG = "backlog", "Phân loại dần kho"
        COMMAND = "command", "Lệnh classify"

    class Status(models.TextChoices):
        RUNNING = "running", "Đang chạy"
        DONE = "done", "Xong"
        FAILED = "failed", "Bị ngắt"

    origin = models.CharField("Nguồn", max_length=10, choices=Origin.choices)
    status = models.CharField(
        "Trạng thái", max_length=10, choices=Status.choices, default=Status.RUNNING
    )
    started_at = models.DateTimeField("Bắt đầu", auto_now_add=True)
    heartbeat_at = models.DateTimeField("Nhịp sống gần nhất", auto_now_add=True)
    finished_at = models.DateTimeField("Kết thúc", null=True, blank=True)
    calls_used = models.PositiveIntegerField("Lượt gọi AI", default=0)
    prompt_tokens = models.PositiveIntegerField("Token vào", default=0)
    completion_tokens = models.PositiveIntegerField("Token ra", default=0)
    classified_count = models.PositiveIntegerField("Repo đã phân loại", default=0)
    error = models.TextField("Lý do ngắt hoặc lỗi", blank=True, default="")

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "lần phân loại"
        verbose_name_plural = "lần phân loại"

    def __str__(self) -> str:
        return f"Phân loại #{self.pk} ({self.get_origin_display()}, {self.get_status_display()})"
