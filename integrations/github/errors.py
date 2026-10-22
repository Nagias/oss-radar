"""Lỗi của client GitHub — mỗi kiểu hỏng một tên riêng để nơi gọi xử lý đúng cách."""

from datetime import datetime


class GitHubError(Exception):
    """Gốc của mọi lỗi khi làm việc với GitHub."""


class GitHubAuthError(GitHubError):
    """Token sai, hết hạn hoặc không đủ quyền (401/403)."""


class GitHubRateLimitError(GitHubError):
    """Hết hạn mức gọi API. `reset_at` là lúc GitHub cho gọi lại, nếu GitHub có báo."""

    def __init__(self, message: str, *, reset_at: datetime | None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class GitHubQueryError(GitHubError):
    """GitHub không chấp nhận truy vấn tìm kiếm (422)."""


class GitHubUnavailableError(GitHubError):
    """Không gọi được GitHub: mất mạng, quá thời gian chờ, hoặc máy chủ GitHub lỗi 5xx."""


class GitHubResponseError(GitHubError):
    """GitHub trả về dữ liệu không đúng định dạng mong đợi."""


class GitHubNotFoundError(GitHubResponseError):
    """GitHub báo không có thứ cần tìm (404): repo đã bị xoá hoặc chuyển sang riêng tư.

    Là một kiểu "phản hồi không mong đợi": nơi nào chưa xử lý riêng 404 (vd tìm kiếm) vẫn coi nó
    như mọi phản hồi lạ khác, không phải lỗi bất ngờ làm sập cả lần quét.
    """
