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
    # Trống = chưa biết (repo lưu trước khi app ghi số này và chưa được quét lại).
    open_issues = models.PositiveIntegerField("Issue/PR đang mở", null=True, blank=True)
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


class StarSnapshot(models.Model):
    """Số star của một repo vào một ngày (giờ Việt Nam). Mỗi repo tối đa một dòng mỗi ngày.

    Làm mốc để lọc thô rising star mà không tốn lượt gọi API; chỉ giữ ngắn hạn
    (xem `prune_snapshots`).
    """

    repository = models.ForeignKey(
        Repository,
        verbose_name="Repo",
        on_delete=models.CASCADE,
        related_name="star_snapshots",
    )
    day = models.DateField("Ngày")
    stars = models.PositiveIntegerField("Số star")
    captured_at = models.DateTimeField("Thời điểm ghi")

    class Meta:
        verbose_name = "ảnh chụp star"
        verbose_name_plural = "ảnh chụp star"
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "day"], name="catalog_unique_snapshot_per_day"
            ),
        ]
        indexes = [models.Index(fields=["day"], name="catalog_snapshot_day_idx")]

    def __str__(self) -> str:
        return f"{self.repository_id} @ {self.day}: {self.stars}"


class OwnerProfile(models.Model):
    """Hồ sơ công khai của chủ repo (cá nhân hay tổ chức), lấy từ GitHub để xét star giả.

    Khoá là `login` viết thường. Chủ đổi tên thì coi như chủ mới (hiếm, chấp nhận). Tài khoản đã
    bị xoá (GitHub trả 404) vẫn có dòng, `is_missing` bật và không còn số liệu — để không gọi lại.
    """

    login = models.CharField("Tài khoản (viết thường)", max_length=39, unique=True)
    github_id = models.BigIntegerField("ID GitHub", null=True, blank=True)
    account_type = models.CharField("Loại tài khoản", max_length=20, blank=True, default="")
    gh_created_at = models.DateTimeField("Ngày tạo tài khoản", null=True, blank=True)
    followers = models.PositiveIntegerField("Người theo dõi", null=True, blank=True)
    public_repos = models.PositiveIntegerField("Repo công khai", null=True, blank=True)
    is_missing = models.BooleanField("Không còn tồn tại", default=False)
    fetched_at = models.DateTimeField("Lấy lúc")

    class Meta:
        verbose_name = "hồ sơ chủ repo"
        verbose_name_plural = "hồ sơ chủ repo"

    def __str__(self) -> str:
        return self.login
