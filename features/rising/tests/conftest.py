"""Hạ tầng test Rising star: GitHub giả (Search + lịch sử star), đồng hồ giả, chạy nền tại chỗ."""

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
import respx
from django.utils import timezone

from features.catalog.models import Repository
from features.catalog.services import upsert_repositories
from features.discovery.models import ScanRun
from features.rising.growth import last_complete_utc_day
from features.rising.models import DailyRun, RisingCheck, WatchQuery
from tests.factories import make_github_repo
from tests.fakes import (
    FakeGitHubSearch,
    FakeStarHistory,
    FakeTime,
    make_search_items,
    make_star_history,
)

SEARCH_URL = "https://api.github.com/search/repositories"
# Client gửi kèm `?per_page=…` → khớp cả phần truy vấn phía sau đường dẫn.
HISTORY_URL_PATTERN = r"^https://api\.github\.com/repositories/\d+/stargazers/history(\?.*)?$"

# Ba truy vấn theo dõi của test; không cái nào là phần đầu của cái khác → đếm được lượt gọi
# theo từng truy vấn.
WATCHED = ("topic:ai-agent", "topic:comfyui", "topic:seo")
FROM, TO = date(2025, 1, 1), date(2026, 6, 30)
OLD = date(2025, 1, 1)  # ngày tạo của repo "cũ": quá 30 ngày tuổi, không bị coi là repo mới

# Báo cáo mẫu: lượt ngày DAY, cửa sổ tăng star kết thúc ở ngày UTC hôm trước.
DAY = date(2026, 10, 22)
WINDOW_END = date(2026, 10, 21)


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


def make_run(
    day: date = DAY,
    *,
    status: str = DailyRun.Status.SUCCEEDED,
    step: int = DailyRun.Step.REPORT,
) -> DailyRun:
    """Một lượt hằng ngày dựng sẵn ở trạng thái/bước cho trước (không chạy gì thật)."""
    return DailyRun.objects.create(day=day, status=status, step=step, window_end=WINDOW_END)


def make_repo(
    github_id: int, *, created: date = date(2025, 1, 1), description: str = "Một repo giả lập"
) -> Repository:
    [outcome] = upsert_repositories(
        [
            make_github_repo(
                github_id=github_id,
                full_name=f"gia-lap/repo-{github_id}",
                html_url=f"https://github.com/gia-lap/repo-{github_id}",
                description=description,
                created_at=datetime.combine(created, time(12), tzinfo=UTC),
            )
        ],
        seen_at=timezone.now(),
    )
    return outcome.repository


def make_check(
    run: DailyRun,
    github_id: int,
    *,
    stars: int,
    gain_7d: int,
    source: str = RisingCheck.Source.HISTORY,
    is_rising: bool = False,
    flags: list[str] | None = None,
) -> RisingCheck:
    """Một dòng xét của lượt; dòng đã xác minh có đủ +1/+7/+30 ngày và chuỗi 30 ngày."""
    verified = source == RisingCheck.Source.HISTORY
    repository = Repository.objects.filter(github_id=github_id).first() or make_repo(github_id)
    return RisingCheck.objects.create(
        daily_run=run,
        repository=repository,
        stars=stars,
        source=source,
        gain_1d=gain_7d // 7 if verified else None,
        gain_7d=gain_7d,
        gain_30d=gain_7d * 3 if verified else None,
        series=[gain_7d // 7] * 30 if verified else [],
        window_end=WINDOW_END if verified else None,
        baseline_day=DAY - timedelta(days=3) if source == RisingCheck.Source.SNAPSHOT else None,
        is_rising=is_rising,
        flags=flags or [],
    )


def days_ago(days: int) -> date:
    return timezone.localdate() - timedelta(days=days)


def item(
    repo_id: int,
    *,
    stars: int,
    created: date = OLD,
    fork: bool = False,
    archived: bool = False,
    description: str | None = "Một repo giả lập",
) -> dict[str, Any]:
    """Một repo trong kết quả Search giả; `created` là ngày tạo (giờ Việt Nam trùng ngày UTC)."""
    [entry] = make_search_items(
        1, start=created, end=created, stars=lambda _: stars, id_start=repo_id
    )
    entry.update(fork=fork, archived=archived, description=description)
    return entry


def snapshot(repo_id: int, *, stars: int, days_back: int = 3) -> None:
    """Ảnh chụp star `days_back` ngày trước (mốc để lọc thô so với hôm nay)."""
    upsert_repositories(
        [make_github_repo(github_id=repo_id, full_name=f"gia-lap/repo-{repo_id}", stars=stars)],
        seen_at=timezone.now() - timedelta(days=days_back),
    )


def window_end() -> date:
    return last_complete_utc_day(timezone.now())


def history(per_day: dict[int, int]) -> list[dict[str, Any]]:
    """Lịch sử star giả: `per_day` là {số ngày trước ngày UTC cuối của cửa sổ: star mới}."""
    end = window_end()
    daily = {end - timedelta(days=back): stars for back, stars in per_day.items()}
    return make_star_history(daily, today=end + timedelta(days=1))
