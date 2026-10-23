"""Luật nhịp gọi GitHub: giãn khoảng cách, chờ hồi lượt, nghỉ khi lỗi tạm thời, ngân sách lượt gọi.

Đồng hồ và hàm ngủ được truyền vào → test chạy tức thì, còn code thật vẫn chờ đúng.
"""

import random
import time
from collections.abc import Callable
from datetime import UTC, datetime

from integrations.github.errors import GitHubRateLimitError

Sleep = Callable[[float], None]

MIN_INTERVAL_WITH_TOKEN = 2.1  # GitHub Search: 30 lượt/phút khi có token
MIN_INTERVAL_ANONYMOUS = 6.1  # 10 lượt/phút khi không có token
DEFAULT_MAX_WAIT_SECONDS = 300.0
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60.0  # Search hồi lượt theo phút

_RANDOM = random.SystemRandom()


def _default_jitter() -> float:
    # "Bước đi không theo nhịp" (nguyên tắc 4): không gọi đều tăm tắp như máy.
    return _RANDOM.uniform(0.0, 0.5)


def select_min_interval(token: str) -> float:
    """Khoảng cách tối thiểu giữa hai lượt gọi tìm kiếm, theo việc có token hay không."""
    return MIN_INTERVAL_WITH_TOKEN if token else MIN_INTERVAL_ANONYMOUS


class CallBudgetExhaustedError(Exception):
    """Đã dùng hết số lượt gọi API được phép cho một lần quét."""


class CallBudget:
    """Ngân sách lượt gọi: mọi lượt gọi HTTP thật (kể cả gọi lại) đều phải `take()` trước."""

    def __init__(self, limit: int) -> None:
        if limit < 0:
            raise ValueError(f"Ngân sách không được âm, đang là {limit}")
        self.limit = limit
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def ensure_available(self) -> None:
        """Hết ngân sách thì báo ngay — trước khi phải chờ giãn nhịp vô ích."""
        if self.remaining <= 0:
            raise CallBudgetExhaustedError(f"Đã dùng hết {self.limit} lượt gọi được phép.")

    def take(self) -> None:
        self.ensure_available()
        self.used += 1


class RequestPacer:
    """Quyết định trước mỗi lượt gọi phải chờ bao lâu."""

    def __init__(
        self,
        *,
        min_interval: float,
        sleep: Sleep,
        max_wait: float = DEFAULT_MAX_WAIT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        jitter: Callable[[], float] = _default_jitter,
    ) -> None:
        self.min_interval = min_interval
        self._sleep = sleep
        self._max_wait = max_wait
        self._clock = clock
        self._wall_clock = wall_clock
        self._jitter = jitter
        self._last_request: float | None = None
        self._quota_back_at: float | None = (
            None  # giờ epoch GitHub hồi lượt, khi lượt trước báo hết
        )
        # Độ lệch "giờ GitHub trừ giờ máy" (đọc từ header Date). Giờ hồi lượt `reset` là giờ của
        # GitHub; máy lệch vài phút mà trừ thẳng giờ máy thì chờ thiếu (bị từ chối liên tiếp) hoặc
        # chờ thừa.
        self._server_offset = 0.0

    def before_request(self) -> None:
        """Chờ cho đủ khoảng cách tối thiểu; nếu lượt trước báo hết lượt thì chờ tới lúc hồi."""
        wait = 0.0
        if self._last_request is not None:
            elapsed = self._clock() - self._last_request
            wait = max(0.0, self.min_interval - elapsed) + self._jitter()
        if self._quota_back_at is not None:
            wait = max(wait, self._quota_back_at - self._github_now())
            back_at = self._quota_back_at
            self._quota_back_at = None
            self._ensure_acceptable(wait, reset_epoch=int(back_at))
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()

    def observe_server_time(self, server_epoch: float | None) -> None:
        """Ghi nhận giờ GitHub (header Date của phản hồi); không có thì giữ nguyên độ lệch cũ."""
        if server_epoch is not None:
            self._server_offset = server_epoch - self._wall_clock()

    def record_response(self, *, remaining: int | None, reset_epoch: int | None) -> None:
        """Ghi nhận hạn mức GitHub báo sau một lượt gọi thành công."""
        if remaining == 0 and reset_epoch is not None:
            self._quota_back_at = reset_epoch + 1.0

    def wait_for_rate_limit(self, *, reset_epoch: int | None, retry_after: float | None) -> None:
        """GitHub vừa từ chối vì hết lượt: chờ theo `retry-after`, hoặc tới lúc hồi lượt."""
        if retry_after is not None:
            wait = retry_after
        elif reset_epoch is not None:
            wait = max(1.0, reset_epoch - self._github_now() + 1.0)
        else:
            wait = DEFAULT_RATE_LIMIT_WAIT_SECONDS
        self._ensure_acceptable(wait, reset_epoch=reset_epoch)
        self._sleep(wait)

    def _github_now(self) -> float:
        return self._wall_clock() + self._server_offset

    def backoff(self, attempt: int) -> None:
        """Nghỉ trước khi gọi lại sau lỗi tạm thời: 2, 4, 8 giây… (+ ngẫu nhiên)."""
        self._sleep(2.0**attempt + self._jitter())

    def _ensure_acceptable(self, wait: float, *, reset_epoch: int | None) -> None:
        if wait > self._max_wait:
            reset_at = datetime.fromtimestamp(reset_epoch, tz=UTC) if reset_epoch else None
            raise GitHubRateLimitError(
                f"GitHub bắt chờ {wait:.0f} giây, quá {self._max_wait:.0f} giây cho phép.",
                reset_at=reset_at,
            )
