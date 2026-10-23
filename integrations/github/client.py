"""Client GitHub REST API: gọi, kiểm phản hồi, đổi JSON thành dataclass, đổi lỗi thành tên rõ."""

import functools
import re
import ssl
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any, Self

import certifi  # đi kèm httpx; httpx khuyên dùng để tự tạo SSLContext
import httpx
from django.conf import settings

from integrations.github.errors import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubQueryError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubUnavailableError,
)
from integrations.github.pacing import CallBudget, RequestPacer, Sleep, select_min_interval
from integrations.github.schemas import (
    GitHubRepo,
    GitHubUser,
    RepoSearchPage,
    StarHistory,
    StarWeek,
)

API_VERSION = "2022-11-28"
MAX_PER_PAGE = 100  # Giới hạn của GitHub Search API cho một trang.
MAX_TRANSIENT_RETRIES = 3  # lỗi tạm thời (mất mạng, quá giờ, 5xx): gọi lại tối đa 3 lần
MAX_RATE_LIMIT_WAITS = 3  # bị từ chối vì hết lượt: chờ rồi gọi lại tối đa 3 lần
HISTORY_WEEKS = 6  # số tuần lịch sử star lấy mặc định
MAX_HISTORY_WEEKS = 30  # GitHub chỉ trả tối đa 30 tuần cho một lượt gọi
_SUNDAY = 6  # datetime.weekday(): thứ Hai = 0 ... Chủ nhật = 6
# Tên tài khoản GitHub: chữ, số, gạch nối, tối đa 39 ký tự. Kiểm trước khi ghép vào đường dẫn.
_LOGIN = re.compile(r"[A-Za-z0-9-]{1,39}")


class GitHubClient:
    """Dùng kèm `with` để đóng kết nối khi xong.

    Mọi lượt gọi đi qua `pacer` (giãn nhịp, chờ hồi lượt) và trừ vào `budget` nếu có.
    """

    def __init__(
        self,
        *,
        token: str,
        api_url: str,
        timeout_seconds: float,
        pacer: RequestPacer,
        budget: CallBudget | None = None,
    ) -> None:
        self._pacer = pacer
        self._budget = budget
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

    def star_history(self, github_id: int, *, weeks: int = HISTORY_WEEKS) -> StarHistory:
        """Star mới mỗi ngày của `weeks` tuần gần nhất, tra theo id repo (tuần mới nhất trước).

        Tra theo id chứ không theo tên để repo đổi tên hay chuyển chủ vẫn không mất dấu.
        """
        if not 1 <= weeks <= MAX_HISTORY_WEEKS:
            raise ValueError(f"weeks phải trong khoảng 1..{MAX_HISTORY_WEEKS}, đang là {weeks}")
        payload = self._get_json(
            f"/repositories/{github_id}/stargazers/history", params={"per_page": weeks}
        )
        return _parse_star_history(payload)

    def get_user(self, login: str) -> GitHubUser:
        """Hồ sơ công khai của tài khoản `login` (cá nhân hay tổ chức). Tính vào hạn mức "core"."""
        if not _LOGIN.fullmatch(login):
            raise ValueError(f"login GitHub không hợp lệ: {login!r}")
        return _parse_user(self._get_json(f"/users/{login}", params={}))

    def _get_json(self, path: str, *, params: dict[str, str | int]) -> object:
        transient_failures = 0
        rate_limit_waits = 0
        while True:
            if self._budget is not None:
                self._budget.ensure_available()
            # Chờ giãn nhịp xong mới trừ ngân sách: bấm Dừng giữa lúc chờ thì lượt chưa gọi không
            # bị tính.
            self._pacer.before_request()
            if self._budget is not None:
                self._budget.take()
            try:
                response = self._http.get(path, params=params)
            except httpx.RequestError as exc:
                transient_failures += 1
                if transient_failures > MAX_TRANSIENT_RETRIES:
                    raise GitHubUnavailableError(f"Không gọi được GitHub: {exc!r}") from exc
                self._pacer.backoff(transient_failures)
                continue
            self._pacer.observe_server_time(_header_epoch(response, "date"))
            if response.status_code >= 500 and transient_failures < MAX_TRANSIENT_RETRIES:
                transient_failures += 1
                self._pacer.backoff(transient_failures)
                continue
            if _is_rate_limited(response) and rate_limit_waits < MAX_RATE_LIMIT_WAITS:
                rate_limit_waits += 1
                self._pacer.wait_for_rate_limit(
                    reset_epoch=_header_int(response, "x-ratelimit-reset"),
                    retry_after=_header_float(response, "retry-after"),
                )
                continue
            break
        _raise_for_status(response)
        self._pacer.record_response(
            remaining=_header_int(response, "x-ratelimit-remaining"),
            reset_epoch=_header_int(response, "x-ratelimit-reset"),
        )
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise GitHubResponseError("GitHub trả về dữ liệu không phải JSON") from exc
        return payload


@functools.cache
def _ssl_context() -> ssl.SSLContext:
    # Nạp bộ chứng chỉ một lần cho cả tiến trình: mỗi lần nạp tốn ~0,3 giây trên Windows.
    return ssl.create_default_context(cafile=certifi.where())


def get_github_client(
    *, sleep: Sleep = time.sleep, budget: CallBudget | None = None
) -> GitHubClient:
    """Client dùng cấu hình của dự án (token trong .env), giãn nhịp theo việc có token hay không."""
    token = settings.GITHUB_TOKEN
    pacer = RequestPacer(min_interval=select_min_interval(token), sleep=sleep)
    return GitHubClient(
        token=token,
        api_url=settings.GITHUB_API_URL,
        timeout_seconds=settings.GITHUB_TIMEOUT_SECONDS,
        pacer=pacer,
        budget=budget,
    )


# --- Xử lý lỗi HTTP -------------------------------------------------------------------------


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    message = _error_message(response)
    if _is_rate_limited(response):
        raise GitHubRateLimitError(message, reset_at=_rate_limit_reset(response))
    if status in (401, 403):
        raise GitHubAuthError(message)
    if status == 404:
        raise GitHubNotFoundError(message)
    if status == 422:
        raise GitHubQueryError(message)
    if status >= 500:
        raise GitHubUnavailableError(f"GitHub lỗi máy chủ {status}: {message}")
    raise GitHubResponseError(f"GitHub trả mã {status}: {message}")


def _is_rate_limited(response: httpx.Response) -> bool:
    if response.status_code not in (403, 429):
        return False
    return (
        response.status_code == 429
        or response.headers.get("x-ratelimit-remaining") == "0"
        or "retry-after" in response.headers
    )


def _rate_limit_reset(response: httpx.Response) -> datetime | None:
    epoch = _header_int(response, "x-ratelimit-reset")
    return datetime.fromtimestamp(epoch, tz=UTC) if epoch is not None else None


def _header_int(response: httpx.Response, name: str) -> int | None:
    raw = response.headers.get(name, "")
    return int(raw) if raw.isdigit() else None


def _header_epoch(response: httpx.Response, name: str) -> float | None:
    """Header ngày giờ kiểu HTTP (vd `Date`) → giờ epoch; thiếu hoặc sai định dạng thì `None`."""
    raw = response.headers.get(name)
    if raw is None:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    epoch: float = parsed.timestamp()
    return epoch


def _header_float(response: httpx.Response, name: str) -> float | None:
    try:
        return float(response.headers[name])
    except (KeyError, ValueError):
        return None


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
        open_issues=_as_optional_count(data.get("open_issues_count")),
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


def _parse_user(payload: object) -> GitHubUser:
    try:
        data = _as_dict(payload)
        return GitHubUser(
            login=_as_str(data["login"]),
            github_id=_as_int(data["id"]),
            account_type=_as_str(data["type"]),
            created_at=_as_datetime(data["created_at"]),
            followers=_as_int(data["followers"]),
            public_repos=_as_int(data["public_repos"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubResponseError(f"Hồ sơ tài khoản GitHub sai định dạng: {exc!r}") from exc


def _parse_star_history(payload: object) -> StarHistory:
    try:
        return StarHistory(weeks=tuple(_parse_star_week(item) for item in _as_list(payload)))
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubResponseError(f"Lịch sử star của GitHub sai định dạng: {exc!r}") from exc


def _parse_star_week(raw: object) -> StarWeek:
    data = _as_dict(raw)
    week = _as_int(data["week"])
    try:
        start = datetime.fromtimestamp(week, tz=UTC)
    except (OverflowError, OSError) as exc:  # mốc thời gian vượt khả năng biểu diễn
        raise ValueError(f"mốc tuần ngoài phạm vi: {week!r}") from exc
    if start.weekday() != _SUNDAY or start != start.replace(hour=0, minute=0, second=0):
        raise ValueError(f"tuần phải bắt đầu Chủ nhật 00:00 UTC, nhận mốc {week!r}")
    values = [_as_int(day) for day in _as_list(data["days"])]
    if len(values) != 7:
        raise ValueError(f"mỗi tuần cần đúng 7 ngày, nhận {len(values)}")
    if min(values) < 0:
        raise ValueError(f"số star mới trong ngày không thể âm: {values!r}")
    # Đã đo 2026-10-22: total luôn bằng tổng 7 ngày. GitHub đổi nghĩa thì phải báo lỗi chứ
    # không được tính sai.
    if _as_int(data["total"]) != sum(values):
        raise ValueError(f"total {data['total']!r} khác tổng các ngày {sum(values)}")
    sun, mon, tue, wed, thu, fri, sat = values
    return StarWeek(start=start.date(), days=(sun, mon, tue, wed, thu, fri, sat))


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


def _as_optional_count(value: object) -> int | None:
    if value is None:
        return None
    count = _as_int(value)
    if count < 0:
        raise ValueError(f"số đếm không thể âm: {value!r}")
    return count


def _as_optional_str(value: object) -> str:
    return "" if value is None else _as_str(value)


def _as_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(_as_str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"thời điểm thiếu múi giờ: {value!r}")
    return parsed
