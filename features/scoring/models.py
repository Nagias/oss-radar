from django.db import models

from features.catalog.models import Repository


class ScoreCache(models.Model):
    """Điểm lưu sẵn của một repo (QĐ-19): lọc, sắp, ẩn trên cả kho mà không tính lại 32.000 repo.

    Chỉ là bản sao để tìm nhanh: phần giải thích hiện trên trang luôn tính trực tiếp từ `rules.py`.
    Không có số tăng star (giống trang lần quét): nghi star giả ở đây chỉ dùng tín hiệu của repo và
    hồ sơ chủ. Tính lại mỗi ngày ở bước lập báo cáo, và sau mỗi lần quét tay.
    """

    repository = models.OneToOneField(
        Repository, on_delete=models.CASCADE, related_name="score_cache"
    )
    quality = models.PositiveSmallIntegerField("Điểm Chất lượng")
    suspicion_points = models.PositiveSmallIntegerField("Điểm nghi star giả")
    suspicion_level = models.CharField("Mức nghi star giả", max_length=12)
    formula_version = models.PositiveSmallIntegerField("Phiên bản công thức")
    computed_at = models.DateTimeField("Tính lúc")

    class Meta:
        indexes = [
            models.Index(fields=["quality"], name="scoring_cache_quality_idx"),
            models.Index(fields=["suspicion_level"], name="scoring_cache_level_idx"),
        ]
        verbose_name = "điểm lưu sẵn"
        verbose_name_plural = "điểm lưu sẵn"

    def __str__(self) -> str:
        return f"{self.repository_id}: {self.quality}"
