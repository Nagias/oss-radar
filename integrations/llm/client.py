"""Client AI chuẩn OpenAI (9router): gọi, kiểm phản hồi, đổi lỗi thành tên rõ, giãn nhịp, ngân sách.

Dùng lại bộ giãn nhịp và ngân sách của client GitHub (`integrations.github.pacing`): cùng luật
"bước đi không theo nhịp" (nguyên tắc 4) và "kỷ luật nước" (nguyên tắc 3).
"""

import time
from types import TracebackType
from typing import Any, Self

import httpx
from django.conf import settings

from integrations.github.errors import GitHubRateLimitError
from integrations.github.pacing import CallBudget, RequestPacer, Sleep
from integrations.llm.errors import (
    LlmAuthError,
    LlmNotConfiguredError,
    LlmRateLimitError,
    LlmResponseError,
    LlmUnavailableError,
)
from integrations.llm.schemas import ChatResult

MAX_TRANSIENT_RETRIES = 3  # lỗi tạm thời (mất mạng, quá giờ, 5xx): gọi lại tối đa 3 lần
MAX_RATE_LIMIT_WAITS = 3  # bị từ chối vì hết lượt (429): chờ rồi gọi lại tối đa 3 lần


class LlmClient:
    """Dùng kèm `with` để đóng kết nối. Mọi lượt gọi đi qua `pacer` và trừ vào `budget` nếu có."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        pacer: RequestPacer,
        budget: CallBudget | None = None,
    ) -> None:
        self._model = model
        self._pacer = pacer
        self._budget = budget
        # Số lượt HTTP đã thật sự gửi (kể cả lượt gọi lại, lượt bị từ chối) — để ghi chi phí.
        self.calls_made = 0
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": "oss-radar"},
            timeout=timeout_seconds,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    @property
    def model(self) -> str:
        return self._model

    def complete(self, messages: list[dict[str, str]]) -> ChatResult:
        """Gửi hội thoại, nhận một câu trả lời JSON trọn khối (không dạng luồng)."""
        body = {
            "model": self._model,
            "messages": messages,
            # 9router mặc định trả dạng luồng (đo 2026-10-27): phải xin rõ một khối.
            "stream": False,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        return _parse_chat(self._post("/chat/completions", body))

    def _post(self, path: str, body: dict[str, Any]) -> object:
        transient_failures = 0
        rate_limit_waits = 0
        while True:
            if self._budget is not None:
                self._budget.ensure_available()
            self._pacer.before_request()
            if self._budget is not None:
                self._budget.take()
            self.calls_made += 1
            try:
                response = self._http.post(path, json=body)
            except httpx.RequestError as exc:
                transient_failures += 1
                if transient_failures > MAX_TRANSIENT_RETRIES:
                    raise LlmUnavailableError(f"Không gọi được 9router: {exc!r}") from exc
                self._pacer.backoff(transient_failures)
                continue
            if response.status_code >= 500 and transient_failures < MAX_TRANSIENT_RETRIES:
                transient_failures += 1
                self._pacer.backoff(transient_failures)
                continue
            if response.status_code == 429 and rate_limit_waits < MAX_RATE_LIMIT_WAITS:
                rate_limit_waits += 1
                self._wait_for_rate_limit(response)
                continue
            break
        _raise_for_status(response)
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise LlmResponseError(
                f"AI trả về dữ liệu không phải JSON: {response.text[:120]!r}"
            ) from exc
        return payload

    def _wait_for_rate_limit(self, response: httpx.Response) -> None:
        try:
            self._pacer.wait_for_rate_limit(
                reset_epoch=None, retry_after=_header_float(response, "retry-after")
            )
        except GitHubRateLimitError as exc:  # bộ giãn nhịp dùng chung đặt tên lỗi theo GitHub
            raise LlmRateLimitError(f"9router bắt chờ quá lâu: {exc}") from exc


def llm_configured() -> bool:
    """Đã điền khoá AI chưa — chưa thì các bước phân loại tự bỏ qua."""
    return bool(settings.LLM_API_KEY)


def get_llm_client(*, sleep: Sleep = time.sleep, budget: CallBudget | None = None) -> LlmClient:
    """Client theo cấu hình dự án (.env). Thiếu khoá thì báo rõ thay vì gọi để bị từ chối."""
    if not llm_configured():
        raise LlmNotConfiguredError(
            "Chưa có LLM_API_KEY trong .env — lấy khoá trong trang quản lý 9router rồi điền vào."
        )
    pacer = RequestPacer(min_interval=settings.LLM_MIN_INTERVAL_SECONDS, sleep=sleep)
    return LlmClient(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        pacer=pacer,
        budget=budget,
    )


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    message = _error_message(response)
    if status in (401, 403):
        raise LlmAuthError(f"9router từ chối khoá ({status}): {message}")
    if status == 429:
        raise LlmRateLimitError(f"9router báo hết lượt gọi: {message}")
    if status >= 500:
        raise LlmUnavailableError(f"9router lỗi máy chủ {status}: {message}")
    raise LlmResponseError(f"9router trả mã {status}: {message}")


def _error_message(response: httpx.Response) -> str:
    try:
        data: object = response.json()
    except ValueError:
        return response.text[:200] or response.reason_phrase
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])
        if isinstance(data.get("message"), str):
            return str(data["message"])
    return response.reason_phrase


def _header_float(response: httpx.Response, name: str) -> float | None:
    try:
        return float(response.headers[name])
    except (KeyError, ValueError):
        return None


def _parse_chat(payload: object) -> ChatResult:
    """Dữ liệu ngoài là không tin cậy: kiểm từng kiểu."""
    try:
        if not isinstance(payload, dict):
            raise TypeError(f"cần object JSON, nhận {type(payload).__name__}")
        choices = payload["choices"]
        if not isinstance(choices, list) or not choices:
            raise ValueError("không có câu trả lời nào (choices rỗng)")
        message = choices[0]["message"]
        content = message["content"]
        if not isinstance(content, str):
            raise TypeError(f"nội dung trả lời không phải chuỗi: {content!r}")
        usage = payload.get("usage") or {}
        if not isinstance(usage, dict):
            raise TypeError(f"usage không phải object: {usage!r}")
        model = payload.get("model", "")
        return ChatResult(
            content=content,
            prompt_tokens=_count(usage.get("prompt_tokens")),
            completion_tokens=_count(usage.get("completion_tokens")),
            model=model if isinstance(model, str) else "",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LlmResponseError(f"Câu trả lời của AI sai định dạng: {exc!r}") from exc


def _count(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f"số token không hợp lệ: {value!r}")
    return value
