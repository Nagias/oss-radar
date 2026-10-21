from django.db import models


class Repository(models.Model):
    """Một repo GitHub trong kho. Khoá chống trùng là `github_id`: không đổi khi repo đổi tên."""

    github_id = models.BigIntegerField("ID GitHub", unique=True)
    full_name = models.CharField("Tên đầy đủ", max_length=200, db_index=True)
    html_url = models.URLField("Đường dẫn", max_length=300)
    description = models.TextField("Mô tả", blank=True, default="")
    language = models.CharField("Ngôn ngữ chính", max_length=100, blank=True, default="")
    topics = models.JSONField("Chủ đề", default=list, blank=True)
    stars = models.PositiveIntegerField("Số star", db_index=True)
    forks = models.PositiveIntegerField("Số fork")
    owner_login = models.CharField("Chủ sở hữu", max_length=100)
    owner_type = models.CharField("Loại chủ sở hữu", max_length=20)
    license_spdx = models.CharField("Giấy phép", max_length=100, blank=True, default="")
    is_fork = models.BooleanField("Là bản fork", default=False)
    is_archived = models.BooleanField("Đã lưu trữ", default=False)
    gh_created_at = models.DateTimeField("Ngày tạo trên GitHub")
    gh_pushed_at = models.DateTimeField("Lần đẩy code gần nhất", null=True, blank=True)
    first_seen_at = models.DateTimeField("Lần đầu thấy")
    last_seen_at = models.DateTimeField("Lần gần nhất thấy")

    class Meta:
        ordering = ["-stars", "full_name"]
        verbose_name = "repo"
        verbose_name_plural = "repo"

    def __str__(self) -> str:
        return self.full_name

    @property
    def is_organization(self) -> bool:
        """Chủ sở hữu là tổ chức (công ty, viện nghiên cứu…) chứ không phải cá nhân."""
        return self.owner_type == "Organization"
