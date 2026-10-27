"""Lỗi của client AI — mỗi kiểu hỏng một tên riêng để nơi gọi xử lý đúng cách."""


class LlmError(Exception):
    """Gốc của mọi lỗi khi gọi AI."""


class LlmNotConfiguredError(LlmError):
    """Chưa điền `LLM_API_KEY` trong .env."""


class LlmAuthError(LlmError):
    """9router từ chối khoá (401/403)."""


class LlmRateLimitError(LlmError):
    """Hết lượt gọi (429) sau khi đã chờ và gọi lại, hoặc bị bắt chờ quá lâu."""


class LlmUnavailableError(LlmError):
    """Không gọi được: 9router tắt, mất mạng, quá thời gian chờ, hoặc lỗi máy chủ 5xx."""


class LlmResponseError(LlmError):
    """Phản hồi không đúng định dạng chuẩn OpenAI mong đợi."""
