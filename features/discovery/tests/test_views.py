"""Trang web của tính năng Quét — lớp mỏng: nhận yêu cầu → gọi services → hiển thị."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest
import respx
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from features.catalog.models import Repository
from features.discovery import services
from features.discovery.models import ScanRun
from features.discovery.tests.conftest import (
    DEFAULT_REQUEST,
    REAL_TOP_REPOS,
    SEARCH_URL,
    run_scan_now,
)
from tests.factories import label_repository
from tests.fakes import FakeGitHubSearch, make_search_items

pytestmark = pytest.mark.django_db

UseFake = Callable[[list[dict[str, Any]]], FakeGitHubSearch]
FROM, TO = date(2025, 1, 1), date(2026, 6, 30)
FORM = {"query": "topic:ai-agent", "min_stars": "0", "budget": "50"}


def detail_url(scan: ScanRun) -> str:
    return reverse("discovery:scan_detail", args=[scan.pk])


def many_repos(count: int) -> list[dict[str, Any]]:
    return make_search_items(count, start=FROM, end=TO, stars=lambda i: (i * 7) % 3000)


def test_home_shows_scan_form(client: Client) -> None:
    page = client.get(reverse("discovery:home")).text

    assert 'name="query"' in page
    assert 'name="min_stars"' in page
    assert 'name="budget"' in page
    assert "Chưa có lần quét nào" in page


def test_blank_query_shows_error_and_does_not_scan(client: Client) -> None:
    response = client.post(reverse("discovery:home"), {**FORM, "query": "  "})

    assert response.status_code == 200
    assert "Hãy nhập truy vấn tìm kiếm GitHub." in response.text
    assert ScanRun.objects.count() == 0


def test_post_starts_background_scan_and_redirects(client: Client, use_fake: UseFake) -> None:
    use_fake(many_repos(50))

    response = client.post(reverse("discovery:home"), FORM)

    scan = ScanRun.objects.get()
    assert response.status_code == 302
    assert response["Location"] == detail_url(scan)
    assert scan.status == ScanRun.Status.SUCCEEDED  # luồng nền chạy tại chỗ trong test


def test_post_refused_while_another_scan_is_live(client: Client) -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    response = client.post(reverse("discovery:home"), FORM)

    assert response.status_code == 200
    assert f"Đang chạy lần quét #{live.pk}" in response.text
    assert ScanRun.objects.count() == 1


def test_home_shows_live_scan_and_locks_scan_button(client: Client) -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    page = client.get(reverse("discovery:home")).text

    assert detail_url(live) in page
    assert "disabled" in page


def test_running_scan_page_auto_refreshes(client: Client) -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    page = client.get(detail_url(live)).text

    assert f'content="3; url={detail_url(live)}"' in page
    assert "Dừng" in page


def test_refused_resume_of_live_scan_refreshes_to_detail_page(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bấm đúp "Tiếp tục": lần bấm thứ hai bị từ chối (409) trong khi lần quét đã chạy. Trang 409
    # nằm ở địa chỉ /resume/ (chỉ nhận POST) — tự tải lại vào đó sẽ ra trang trắng 405.
    live = services.start_scan(DEFAULT_REQUEST)
    monkeypatch.setattr("core.background.busy_label", lambda: f"Lần quét #{live.pk}")

    response = client.post(reverse("discovery:scan_resume", args=[live.pk]), {"extra_budget": "50"})

    assert response.status_code == 409
    assert f'content="3; url={detail_url(live)}"' in response.text


def test_finished_scan_page_does_not_refresh(client: Client, github_search: respx.Route) -> None:
    scan = run_scan_now()

    page = client.get(detail_url(scan)).text

    assert 'http-equiv="refresh"' not in page


def test_scan_detail_lists_repositories_by_stars(
    client: Client, github_search: respx.Route
) -> None:
    scan = run_scan_now()

    page = client.get(detail_url(scan)).text

    positions = [page.index(name) for name in REAL_TOP_REPOS]
    assert positions == sorted(positions)
    assert "255.793" in page  # số star định dạng kiểu Việt Nam
    assert 'rel="noopener noreferrer"' in page
    assert "40.194" in page  # GitHub báo bao nhiêu — nói thật phần còn thiếu


def test_coverage_and_calls_are_shown(client: Client, use_fake: UseFake) -> None:
    use_fake(many_repos(250))
    scan = run_scan_now(created_from=FROM, created_to=TO, budget=50)

    page = client.get(detail_url(scan)).text

    assert "100%" in page
    assert "3/50" in page  # lượt gọi đã dùng / ngân sách


def test_problem_slices_are_listed(client: Client, use_fake: UseFake) -> None:
    day = date(2026, 1, 5)
    use_fake(make_search_items(1050, start=day, end=day, stars=lambda i: 5))
    scan = run_scan_now(created_from=day, created_to=day, budget=50)

    page = client.get(detail_url(scan)).text

    assert "Bị cắt" in page
    assert "thiếu 50" in page


def test_waiting_time_is_shown(client: Client) -> None:
    live = services.start_scan(DEFAULT_REQUEST)
    until = timezone.now() + timedelta(seconds=60)
    ScanRun.objects.filter(pk=live.pk).update(waiting_until=until)

    page = client.get(detail_url(live)).text

    assert "Đang chờ GitHub tới" in page


def test_failed_scan_shows_reason(client: Client, http_mock: respx.MockRouter) -> None:
    http_mock.get(SEARCH_URL).respond(401, json={"message": "Bad credentials"})
    scan = run_scan_now()

    page = client.get(detail_url(scan)).text

    assert scan.error_message in page


def test_stop_button_requests_stop(client: Client) -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    response = client.post(reverse("discovery:scan_stop", args=[live.pk]))

    live.refresh_from_db()
    assert response.status_code == 302
    assert live.stop_requested is True


def test_resume_runs_remaining_slices(client: Client, use_fake: UseFake) -> None:
    use_fake(many_repos(2500))
    partial = run_scan_now(created_from=FROM, created_to=TO, budget=5)

    response = client.post(
        reverse("discovery:scan_resume", args=[partial.pk]), {"extra_budget": "1000"}
    )

    partial.refresh_from_db()
    assert response.status_code == 302
    assert partial.status == ScanRun.Status.SUCCEEDED
    assert partial.fetched_count == 2500


def test_resume_refused_while_another_scan_is_live(
    client: Client, github_search: respx.Route
) -> None:
    partial = run_scan_now()
    live = services.start_scan(DEFAULT_REQUEST)

    response = client.post(
        reverse("discovery:scan_resume", args=[partial.pk]), {"extra_budget": "50"}
    )

    assert response.status_code == 409
    assert f"Đang chạy lần quét #{live.pk}" in response.text


def test_paused_scan_offers_resume(client: Client, github_search: respx.Route) -> None:
    scan = run_scan_now()

    page = client.get(detail_url(scan)).text

    assert reverse("discovery:scan_resume", args=[scan.pk]) in page
    assert 'name="extra_budget"' in page


@pytest.mark.parametrize("name", ["discovery:scan_stop", "discovery:scan_resume"])
def test_stop_and_resume_require_post(client: Client, name: str) -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    assert client.get(reverse(name, args=[live.pk])).status_code == 405


def test_unknown_scan_returns_404(client: Client) -> None:
    assert client.get(reverse("discovery:scan_detail", args=[999])).status_code == 404


def test_home_lists_recent_scans(client: Client, github_search: respx.Route) -> None:
    run_scan_now(query="topic:ai-video")

    page = client.get(reverse("discovery:home")).text

    assert "topic:ai-video" in page


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github


def test_resume_with_invalid_budget_shows_error(client: Client, github_search: respx.Route) -> None:
    partial = run_scan_now()

    response = client.post(
        reverse("discovery:scan_resume", args=[partial.pk]), {"extra_budget": "7"}
    )

    assert response.status_code == 409
    partial.refresh_from_db()
    assert partial.status == ScanRun.Status.SUCCEEDED_PARTIAL


BUSY = "Lượt quét hằng ngày 22/10"
BUSY_MESSAGE = f"App đang chạy việc nền: {BUSY} — chờ xong, hoặc dừng việc đó rồi thử lại."


@pytest.fixture
def background_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.background.busy_label", lambda: BUSY)


@pytest.fixture
def background_taken_meanwhile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vừa kiểm thấy rảnh thì bộ nhịp đã kịp chiếm luồng nền: `submit_if_idle` không xếp gì."""
    monkeypatch.setattr("core.background.submit_if_idle", lambda *args, **kwargs: None)


@pytest.mark.usefixtures("background_busy")
def test_home_refuses_new_scan_while_background_busy(client: Client) -> None:
    response = client.post(reverse("discovery:home"), FORM)

    assert response.status_code == 200
    assert BUSY_MESSAGE in response.text
    assert ScanRun.objects.count() == 0


@pytest.mark.usefixtures("background_busy")
def test_home_locks_scan_button_and_shows_label_while_background_busy(client: Client) -> None:
    page = client.get(reverse("discovery:home")).text

    assert "disabled" in page
    assert BUSY in page


def test_home_scan_button_open_when_idle(client: Client) -> None:
    assert "disabled" not in client.get(reverse("discovery:home")).text


def test_home_shows_live_daily_scan(client: Client) -> None:
    daily = services.start_scan(replace(DEFAULT_REQUEST, origin=ScanRun.Origin.DAILY))

    page = client.get(reverse("discovery:home")).text

    assert detail_url(daily) in page
    assert "disabled" in page


def test_resume_refused_with_409_while_background_busy(
    client: Client, github_search: respx.Route, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = run_scan_now()
    monkeypatch.setattr("core.background.busy_label", lambda: BUSY)

    response = client.post(
        reverse("discovery:scan_resume", args=[partial.pk]), {"extra_budget": "50"}
    )

    assert response.status_code == 409
    assert BUSY_MESSAGE in response.text
    partial.refresh_from_db()
    assert (partial.status, partial.budget) == (ScanRun.Status.SUCCEEDED_PARTIAL, 1)


def test_resume_button_locked_with_label_while_background_busy(
    client: Client, github_search: respx.Route, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = run_scan_now()
    monkeypatch.setattr("core.background.busy_label", lambda: BUSY)

    page = client.get(detail_url(partial)).text

    assert "disabled" in page
    assert BUSY in page


@pytest.mark.usefixtures("background_taken_meanwhile")
def test_new_scan_released_when_background_taken_meanwhile(client: Client) -> None:
    response = client.post(reverse("discovery:home"), FORM)

    scan = ScanRun.objects.get()
    assert response["Location"] == detail_url(scan)
    assert scan.status == ScanRun.Status.PAUSED
    assert services.REASON_BUSY in client.get(detail_url(scan)).text


def test_resume_released_when_background_taken_meanwhile(
    client: Client, github_search: respx.Route, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = run_scan_now()
    monkeypatch.setattr("core.background.submit_if_idle", lambda *args, **kwargs: None)

    response = client.post(
        reverse("discovery:scan_resume", args=[partial.pk]), {"extra_budget": "50"}
    )

    partial.refresh_from_db()
    assert response["Location"] == detail_url(partial)
    assert (partial.status, partial.stop_reason) == (ScanRun.Status.PAUSED, services.REASON_BUSY)
    assert partial.budget == 1  # chưa chạy được thì trả lại phần ngân sách vừa thêm


def test_scan_detail_shows_auto_resume_and_pruned_notes(
    client: Client, github_search: respx.Route
) -> None:
    scan = run_scan_now(origin=ScanRun.Origin.DAILY)
    resumed_at = timezone.now()
    ScanRun.objects.filter(pk=scan.pk).update(
        auto_resume_count=2, last_auto_resume_at=resumed_at, results_pruned=True
    )

    page = client.get(detail_url(scan)).text

    assert "Hằng ngày" in page
    assert f"Tự chạy tiếp lần 2 lúc {timezone.localtime(resumed_at):%H:%M}" in page
    assert "Danh sách repo đã dọn sau 35 ngày" in page


def test_manual_scan_detail_has_no_daily_or_auto_resume_notes(
    client: Client, github_search: respx.Route
) -> None:
    page = client.get(detail_url(run_scan_now())).text

    assert "Hằng ngày" not in page
    assert "Tự chạy tiếp lần" not in page
    assert "đã dọn" not in page


def test_resume_finished_scan_is_refused(client: Client, github_search: respx.Route) -> None:
    scan = run_scan_now()
    ScanRun.objects.filter(pk=scan.pk).update(status=ScanRun.Status.SUCCEEDED)

    response = client.post(reverse("discovery:scan_resume", args=[scan.pk]), {"extra_budget": "50"})

    assert response.status_code == 409
    assert "không ở trạng thái tiếp tục được" in response.text


def test_scan_failed_because_github_was_down_offers_resume(client: Client) -> None:
    scan = ScanRun.objects.create(
        query="topic:ai-agent",
        status=ScanRun.Status.FAILED,
        error_kind=ScanRun.ErrorKind.UNAVAILABLE,
        error_message=services.REASON_NOTHING_FETCHED,
        budget=50,
    )

    page = client.get(detail_url(scan)).text

    assert services.REASON_NOTHING_FETCHED in page
    assert reverse("discovery:scan_resume", args=[scan.pk]) in page


def test_scan_failed_on_token_offers_no_resume(client: Client) -> None:
    scan = ScanRun.objects.create(
        query="topic:ai-agent",
        status=ScanRun.Status.FAILED,
        error_kind=ScanRun.ErrorKind.AUTH,
        error_message="GitHub từ chối token.",
        budget=50,
    )

    page = client.get(detail_url(scan)).text

    assert reverse("discovery:scan_resume", args=[scan.pk]) not in page


# --- Điểm Chất lượng và repo nghi star giả (F-006) ---------------------------------------------


def scored_items() -> list[dict[str, Any]]:
    """repo-1 "Nghi cao" (2 fork / 613 star, không commit sau ngày tạo), repo-2 "Cần xem"
    (4 fork / 1.000 star), repo-3 bình thường."""
    items = make_search_items(3, start=FROM, end=TO, stars=lambda i: (613, 1000, 5000)[i])
    items[0].update(forks_count=2, pushed_at=items[0]["created_at"])
    items[1].update(forks_count=4)
    items[2].update(forks_count=600)
    return items


def test_scan_detail_shows_quality_and_hides_high_suspicion(
    client: Client, use_fake: UseFake
) -> None:
    use_fake(scored_items())
    scan = run_scan_now()

    page = client.get(detail_url(scan)).text

    assert '<th class="num">Chất lượng</th>' in page
    assert '<th class="num">Nghi star giả</th>' in page
    assert "Tiềm năng" not in page  # số tăng star nằm ở tính năng rising, trang này không có
    assert "Phổ biến <strong>" in page
    main, hidden = page.split("Đã ẩn 1 repo nghi star giả — Hiện")
    assert "gia-lap/repo-1" not in main
    assert "gia-lap/repo-1" in hidden
    assert "2 fork trên 613 star (dưới 0,5%)" in hidden
    assert "Cần xem" in main
    assert main.index("gia-lap/repo-3") < main.index("gia-lap/repo-2")  # vẫn sắp theo star


def test_scan_detail_without_suspicious_repos_has_no_hidden_section(
    client: Client, github_search: respx.Route
) -> None:
    scan = run_scan_now()

    page = client.get(detail_url(scan)).text

    assert "nghi star giả — Hiện" not in page


def test_scored_results_split_hidden_and_keep_limit(use_fake: UseFake) -> None:
    use_fake(scored_items())
    scan = run_scan_now()

    scored = services.scored_results(scan, limit=2)

    assert [row.result.repository.full_name for row in scored.shown] == [
        "gia-lap/repo-3",
        "gia-lap/repo-2",
    ]
    assert scored.hidden == []  # repo-1 nằm ngoài 2 repo nhiều star nhất
    everything = services.scored_results(scan, limit=500)
    assert [row.result.repository.full_name for row in everything.hidden] == ["gia-lap/repo-1"]
    assert everything.hidden[0].scores.suspicion.points == 65


def test_scan_detail_shows_labels_and_links_to_full_list(client: Client, use_fake: UseFake) -> None:
    use_fake(scored_items())
    scan = run_scan_now()
    label_repository(Repository.objects.get(github_id=3), audience=("creator",), aspects=("video",))

    page = client.get(detail_url(scan)).text

    assert "Video &amp; làm phim AI" in page
    assert f'href="/repos/?scan={scan.pk}"' in page
