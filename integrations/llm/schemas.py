"""Dữ liệu AI đã kiểm kiểu. Phần còn lại của app chỉ thấy dataclass này, không thấy JSON."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Một câu trả lời của AI kèm số token đã tiêu (để ghi lại chi phí)."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
