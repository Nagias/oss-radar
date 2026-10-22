"""Hạ tầng test Rising star: GitHub giả (Search + lịch sử star), đồng hồ giả, chạy nền tại chỗ."""

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
import respx
from django.utils import timezone

from features.discovery.models import ScanRun
from features.rising.models import DailyRun, WatchQuery
from tests.fakes import FakeGitHubSearch, FakeStarHistory, FakeTime, make_search_items

SEARCH_URL = "https://api.github.com/search/repositories"
# Client gửi kèm `?per_page=…` → khớp cả phần truy vấn phía sau đường dẫn.
HISTORY_URL_PATTERN = r"^https://api\.github\.com/repositories/\d+/stargazers/history(\?.*)?$"

# Ba truy vấn theo dõi của test; không cái nào là phần đầu của cái khác → đếm được lượt gọi
# theo từng truy vấn.
WATCHED = ("topic:ai-agent", "topic:comfyui", "topic:seo")
FROM, TO = date(2025, 1, 1), date(2026, 6, 30)


@dataclass(frozen=True, slots=True)
class FakeGitHub:
    search: FakeGitHubSearch
    history: FakeStarHistory


UseFake = Callable[..., FakeGitHub]


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch, fake_time: FakeTime) -> None:
    """Mọi chỗ chờ (giãn nhịp, chờ hồi lượt, nghỉ khi lỗi) dùng đồng hồ giả — test chạy tức thì."""
    monkeypatch.setattr("time.sleep", fake_time.sleep)


@pytest.fixture(autouse=True)
def _inline_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """Việc nền chạy ngay tại chỗ để test thấy kết quả liền; lỗi bất ngờ nổ thẳng ra test.

    Luồng nền mặc định rảnh; test cần "đang bận" thì tự monkeypatch `core.background.busy_label`.
    """

    def run_now(job: Callable[[int], None], arg: int, *, label: str = "") -> Future[None]:
        job(arg)
        done: Future[None] = Future()
        done.set_result(None)
        return done

    monkeypatch.setattr("core.background.submit", run_now)
    monkeypatch.setattr("core.background.submit_if_idle", run_now)
    monkeypatch.setattr("core.background.busy_label", lambda: None)


@pytest.fixture
def use_fake_github(http_mock: respx.MockRouter) -> UseFake:
    """Gắn GitHub giả: Search hiểu truy vấn; lịch sử star theo id."""

    def attach(
        items: list[dict[str, Any]], histories: dict[int, list[dict[str, Any]]] | None = None
    ) -> FakeGitHub:
        fake = FakeGitHub(FakeGitHubSearch(items), FakeStarHistory(histories or {}))
        http_mock.get(SEARCH_URL).mock(side_effect=fake.search)
        http_mock.get(url__regex=HISTORY_URL_PATTERN).mock(side_effect=fake.history)
        return fake

    return attach


@pytest.fixture
def watch_list(db: None) -> list[WatchQuery]:
    """Danh sách theo dõi riêng: bỏ 16 truy vấn gợi ý migration tạo sẵn, thay bằng `WATCHED`."""
    WatchQuery.objects.all().delete()
    return [
        WatchQuery.objects.create(label="Thử", query=query, position=position)
        for position, query in enumerate(WATCHED, start=1)
    ]


def some_repos(count: int = 250) -> list[dict[str, Any]]:
    """`count` repo từ 10 star trở lên: truy vấn theo dõi nào (≥ 10 star) cũng thấy đủ cả."""
    return make_search_items(count, start=FROM, end=TO, stars=lambda i: 10 + i)


def calls_for(fake: FakeGitHub, query: str) -> int:
    """Số lượt gọi Search của một truy vấn theo dõi (gửi đi = truy vấn gốc + stars/created)."""
    return sum(1 for sent in fake.search.queries if sent.split(" ")[0] == query)


def at(hour: int, minute: int = 0, *, day: date | None = None) -> datetime:
    """Thời điểm giờ Việt Nam (múi giờ của dự án) trong ngày `day` (mặc định hôm nay)."""
    return timezone.make_aware(datetime.combine(day or timezone.localdate(), time(hour, minute)))


class AppKilledError(BaseException):
    """Giả lập app bị tắt ngang: không phải `Exception` nên không nơi nào bắt để ghi trạng thái."""


def make_heartbeats_stale() -> None:
    """App đã tắt từ 10 phút trước: mọi nhịp sống mới hơn mốc đó lùi về đúng mốc đó.

    Kể cả lần quét đã xong: lần quét con vừa xong (nhịp sống còn mới) vẫn giữ cho lượt "đang chạy".
    """
    long_ago = timezone.now() - timedelta(minutes=10)
    DailyRun.objects.filter(heartbeat_at__gt=long_ago).update(heartbeat_at=long_ago)
    ScanRun.objects.filter(heartbeat_at__gt=long_ago).update(heartbeat_at=long_ago)
