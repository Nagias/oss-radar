"""Dữ liệu GitHub đã kiểm kiểu. Phần còn lại của app chỉ thấy các dataclass này, không thấy JSON."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class GitHubRepo:
    """Một repo như GitHub mô tả. `github_id` không đổi khi repo đổi tên hay chuyển chủ."""

    github_id: int
    full_name: str
    html_url: str
    description: str
    language: str
    topics: tuple[str, ...]
    stars: int
    forks: int
    open_issues: int  # GitHub gộp số issue và pull request đang mở
    owner_login: str
    owner_type: str
    license_spdx: str
    is_fork: bool
    is_archived: bool
    created_at: datetime
    pushed_at: datetime | None


@dataclass(frozen=True, slots=True)
class RepoSearchPage:
    """Một trang kết quả tìm kiếm. `total_count` là tổng GitHub báo, có thể lớn hơn số lấy về."""

    total_count: int
    incomplete_results: bool
    items: tuple[GitHubRepo, ...]


@dataclass(frozen=True, slots=True)
class GitHubUser:
    """Hồ sơ công khai của một tài khoản (cá nhân hay tổ chức) — dùng để xét chủ repo."""

    login: str
    github_id: int
    account_type: str
    created_at: datetime
    followers: int
    public_repos: int


@dataclass(frozen=True, slots=True)
class StarWeek:
    """Star mới của một tuần. `start` là Chủ nhật (UTC); `days` đi từ Chủ nhật tới thứ Bảy."""

    start: date
    days: tuple[int, int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class StarHistory:
    """Lịch sử star theo tuần, tuần mới nhất đứng trước — đúng thứ tự GitHub trả."""

    weeks: tuple[StarWeek, ...]
