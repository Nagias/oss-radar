"""Client GitHub REST API: gọi, kiểm phản hồi, đổi JSON thành dataclass, đổi lỗi thành tên rõ."""

import functools
import ssl
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

import certifi  # đi kèm httpx; httpx khuyên dùng để tự tạo SSLContext
import httpx
from django.conf import settings

from integrations.github.errors import (
    GitHubAuthError,
    GitHubQueryError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubUnavailableError,
)
from integrations.github.schemas import GitHubRepo, RepoSearchPage

API_VERSION = "2022-11-28"
MAX_PER_PAGE = 100  # Giới hạn của GitHub Search API cho một trang.


class GitHubClient:
    """Dùng kèm `with` để đóng kết nối khi xong."""

    def __init__(self, *, token: str, api_url: str, timeout_seconds: float) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "oss-radar",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=api_url, headers=headers, timeout=timeout_seconds, verify=_ssl_context()
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

    def search_repositories(
        self, query: str, *, per_page: int = MAX_PER_PAGE, page: int = 1
    ) -> RepoSearchPage:
        """Tìm repo theo cú pháp tìm kiếm của GitHub, sắp theo star giảm dần."""
        if not query.strip():
            raise ValueError("query không được để trống")
        if not 1 <= per_page <= MAX_PER_PAGE:
            raise ValueError(f"per_page phải trong khoảng 1..{MAX_PER_PAGE}, đang là {per_page}")
        if page < 1:
            raise ValueError(f"page phải từ 1 trở lên, đang là {page}")
        params: dict[str, str | int] = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": per_page,
            "page": page,
        }
        return _parse_search_page(self._get_json("/search/repositories", params=params))

    def _get_json(self, path: str, *, params: dict[str, str | int]) -> object:
        # DEBT(D-005): gọi một lần, lỗi là dừng — chưa thử lại/giãn nhịp khi lỗi tạm thời, hết lượt.
        try:
            response = self._http.get(path, params=params)
        except httpx.RequestError as exc:
            raise GitHubUnavailableError(f"Không gọi được GitHub: {exc!r}") from exc
        _raise_for_status(response)
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise GitHubResponseError("GitHub trả về dữ liệu không phải JSON") from exc
        return payload


@functools.cache
def _ssl_context() -> ssl.SSLContext:
    # Nạp bộ chứng chỉ một lần cho cả tiến trình: mỗi lần nạp tốn ~0,3 giây trên Windows.
    return ssl.create_default_context(cafile=certifi.where())


def get_github_client() -> GitHubClient:
    """Client dùng cấu hình của dự án (token trong .env)."""
    return GitHubClient(
        token=settings.GITHUB_TOKEN,
        api_url=settings.GITHUB_API_URL,
        timeout_seconds=settings.GITHUB_TIMEOUT_SECONDS,
    )


# --- Xử lý lỗi HTTP -------------------------------------------------------------------------


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    message = _error_message(response)
    if status in (403, 429) and _is_rate_limited(response):
        raise GitHubRateLimitError(message, reset_at=_rate_limit_reset(response))
    if status in (401, 403):
        raise GitHubAuthError(message)
    if status == 422:
        raise GitHubQueryError(message)
    if status >= 500:
        raise GitHubUnavailableError(f"GitHub lỗi máy chủ {status}: {message}")
    raise GitHubResponseError(f"GitHub trả mã {status}: {message}")


def _is_rate_limited(response: httpx.Response) -> bool:
    return (
        response.status_code == 429
        or response.headers.get("x-ratelimit-remaining") == "0"
        or "retry-after" in response.headers
    )


def _rate_limit_reset(response: httpx.Response) -> datetime | None:
    raw = response.headers.get("x-ratelimit-reset", "")
    return datetime.fromtimestamp(int(raw), tz=UTC) if raw.isdigit() else None


def _error_message(response: httpx.Response) -> str:
    try:
        data: object = response.json()
    except ValueError:
        return response.text[:200] or response.reason_phrase
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        return str(data["message"])
    return response.reason_phrase


# --- Đổi JSON thành dataclass (dữ liệu ngoài là không tin cậy: kiểm từng kiểu) -------------------


def _parse_search_page(payload: object) -> RepoSearchPage:
    try:
        data = _as_dict(payload)
        return RepoSearchPage(
            total_count=_as_int(data["total_count"]),
            incomplete_results=_as_bool(data["incomplete_results"]),
            items=tuple(_parse_repo(item) for item in _as_list(data["items"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubResponseError(f"Dữ liệu tìm kiếm của GitHub sai định dạng: {exc!r}") from exc


def _parse_repo(raw: object) -> GitHubRepo:
    data = _as_dict(raw)
    owner = _as_dict(data["owner"])
    license_info = data.get("license")
    pushed_at = data.get("pushed_at")
    return GitHubRepo(
        github_id=_as_int(data["id"]),
        full_name=_as_str(data["full_name"]),
        html_url=_as_str(data["html_url"]),
        description=_as_optional_str(data.get("description")),
        language=_as_optional_str(data.get("language")),
        topics=tuple(_as_str(topic) for topic in _as_list(data.get("topics", []))),
        stars=_as_int(data["stargazers_count"]),
        forks=_as_int(data["forks_count"]),
        owner_login=_as_str(owner["login"]),
        owner_type=_as_str(owner["type"]),
        license_spdx=(
            _as_optional_str(license_info.get("spdx_id")) if isinstance(license_info, dict) else ""
        ),
        is_fork=_as_bool(data["fork"]),
        is_archived=_as_bool(data["archived"]),
        created_at=_as_datetime(data["created_at"]),
        pushed_at=None if pushed_at is None else _as_datetime(pushed_at),
    )


def _as_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"cần object JSON, nhận {type(value).__name__}")
    return value


def _as_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"cần mảng JSON, nhận {type(value).__name__}")
    return value


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"cần số nguyên, nhận {value!r}")
    return value


def _as_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"cần true/false, nhận {value!r}")
    return value


def _as_str(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"cần chuỗi, nhận {value!r}")
    return value


def _as_optional_str(value: object) -> str:
    return "" if value is None else _as_str(value)


def _as_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(_as_str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"thời điểm thiếu múi giờ: {value!r}")
    return parsed
