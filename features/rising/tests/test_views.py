"""Trang chi tiết lượt và trang Theo dõi — lớp mỏng: nhận yêu cầu → gọi services → hiển thị."""

import html
import re
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, time, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.template.loader import render_to_string
from django.test import Client, RequestFactory
from django.urls import ResolverMatch, reverse
from django.utils import timezone
from pytest_django.fixtures import Settings

from features.catalog.models import Repository
from features.discovery.models import ScanRun
from features.rising import services
from features.rising.growth import FLAG_LABELS, Flag, sparkline_points
from features.rising.models import DailyRun, DailyRunScan, RisingCheck, WatchQuery
from features.rising.tests.conftest import (
    DAY,
    WATCHED,
    UseFake,
    at,
    make_check,
    make_repo,
    make_run,
    some_repos,
)
from tests.factories import label_repository
from tests.html import Button, buttons, nav_links

pytestmark = pytest.mark.django_db

Status = DailyRun.Status
Source = RisingCheck.Source
REPORT_URL = reverse("rising:report")  # đường cũ: nay chỉ chuyển hướng (F-012)
WATCH_URL = reverse("rising:watch")
RUN_URL = reverse("rising:run_now")
WATCH_FORM = {
    "label": "Video AI",
    "query": "topic:ai-video",
    "min_stars": "10",
    "max_stars": "",
    "budget": "300",
    "enabled": "on",
    "position": "5",
}


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github


def today_run(**fields: object) -> DailyRun:
    defaults: dict[str, object] = {"status": Status.RUNNING, "heartbeat_at": timezone.now()}
    return DailyRun.objects.create(
        day=timezone.localdate(), **{**defaults, **fields}, window_end=DAY
    )


def detail(run: DailyRun) -> str:
    """Trang chi tiết lượt (thân báo cáo rising cũ, F-012)."""
    return reverse("rising:run_detail", args=[run.pk])


def link_scan(run: DailyRun, query: str, *, position: int = 1) -> ScanRun:
    scan = ScanRun.objects.create(
        query=query, origin=ScanRun.Origin.DAILY, status=ScanRun.Status.SUCCEEDED
    )
    watch = WatchQuery.objects.filter(query=query).first()
    DailyRunScan.objects.create(daily_run=run, watch_query=watch, scan_run=scan, position=position)
    return scan


# --- Trang chi tiết lượt ---------------------------------------------------------------------


def test_report_page_shows_rising_rows_with_reason_flags_and_noopener(client: Client) -> None:
    run = make_run()
    make_repo(1, description="<script>alert(1)</script>")  # mô tả từ GitHub: phải được escape
    first = make_check(
        run, 1, stars=340, gain_7d=120, is_rising=True, flags=["burst", "no_description"]
    )
    make_check(run, 2, stars=45, gain_7d=210, is_rising=True)
    make_check(run, 3, stars=1500, gain_7d=999)  # trên ngưỡng 1.000 star: không có trong bảng
    DailyRun.objects.filter(pk=run.pk).update(
        candidate_count=3, new_repo_count=42, insufficient_count=7
    )

    page = client.get(detail(run)).text

    assert page.index("gia-lap/repo-2") < page.index("gia-lap/repo-1")  # tăng nhiều lên trước
    assert "gia-lap/repo-3" not in page
    assert (
        '<a href="https://github.com/gia-lap/repo-1" target="_blank" rel="noopener noreferrer">'
        in page
    )
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert (
        "+120 star trong 7 ngày (ngưỡng 50) · đang 340 star (dưới 1.000) · "
        "nguồn: lịch sử star GitHub, ngày UTC 15/10–21/10"  # noqa: RUF001 — đúng mẫu thiết kế
    ) in page
    assert FLAG_LABELS[Flag.BURST] in page
    assert FLAG_LABELS[Flag.NO_DESCRIPTION] in page
    assert f'<polyline points="{sparkline_points(first.series)}"' in page
    assert page.count("<polyline") == 2
    assert page.count("Mới vào danh sách") == 2  # chưa có báo cáo trước → cả hai là mới
    assert "+17" in page  # +1 ngày
    assert "+360" in page  # +30 ngày của dòng đầu


def test_report_page_summarises_scans_candidates_and_missing_data(client: Client) -> None:
    run = make_run()
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)
    make_check(run, 2, stars=200, gain_7d=10)
    make_check(run, 3, stars=100, gain_7d=80, source=Source.SNAPSHOT)
    make_check(run, 4, stars=50, gain_7d=60, source=Source.AGE)
    DailyRun.objects.filter(pk=run.pk).update(
        candidate_count=4, new_repo_count=1234, insufficient_count=180, unverified_count=2
    )
    scan = link_scan(run, "topic:ai-agent")

    page = client.get(detail(run)).text

    assert reverse("discovery:scan_detail", args=[scan.pk]) in page
    assert "topic:ai-agent" in page
    assert "1.234" in page  # repo mới phát hiện
    assert "180 repo mới vào tầm theo dõi" in page
    assert "sẽ được xét" in page
    assert "ước lượng từ ảnh chụp ngày 19/10 và ngày 22/10, chưa xác minh" in page
    assert "ước lượng theo tuổi repo" in page
    assert page.count("<strong>gia-lap/repo-3</strong>") == 1  # chỉ ở mục chưa xác minh
    assert re.search(r"Ứng viên[^<]*<strong>4</strong>", page)


def test_report_page_lists_problems_of_an_older_report(client: Client) -> None:
    old = make_run(DAY - timedelta(days=1), status=Status.SUCCEEDED_PARTIAL)
    DailyRun.objects.filter(pk=old.pk).update(problems=["Truy vấn «topic:x» lỗi: mạng."])

    page = client.get(detail(old)).text

    assert "Truy vấn «topic:x» lỗi: mạng." in page
    assert "Xong nhưng còn sót" in page


def test_report_filters_from_query_string(client: Client) -> None:
    older = make_run(DAY - timedelta(days=1))
    make_check(older, 9, stars=100, gain_7d=70, is_rising=True)
    run = make_run()
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)
    make_check(run, 2, stars=900, gain_7d=60, is_rising=True)
    make_check(run, 3, stars=1500, gain_7d=40)

    default = client.get(detail(run)).text
    narrow = client.get(detail(run), {"max_stars": "500", "min_gain": "100"}).text
    wide = client.get(detail(run), {"max_stars": "2000", "min_gain": "0"}).text
    other_day = client.get(detail(older)).text

    assert [name in default for name in ("repo-1<", "repo-2<", "repo-3<")] == [True, True, False]
    assert [name in narrow for name in ("repo-1<", "repo-2<", "repo-3<")] == [True, False, False]
    assert [name in wide for name in ("repo-1<", "repo-2<", "repo-3<")] == [True, True, True]
    assert "repo-9<" in other_day
    assert "repo-1<" not in other_day
    assert 'value="500"' in narrow  # ô lọc giữ giá trị vừa chọn


def test_report_with_invalid_filter_shows_error_and_falls_back_to_defaults(
    client: Client,
) -> None:
    run = make_run()
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)

    page = client.get(detail(run), {"min_gain": "-5", "max_stars": "abc"}).text

    assert 'class="error"' in page
    assert "repo-1<" in page  # vẫn hiện báo cáo theo ngưỡng mặc định


def test_watch_auto_refresh_only_while_live(client: Client) -> None:
    make_run(DAY - timedelta(days=1))
    run = today_run(step=DailyRun.Step.VERIFY)

    live_page = client.get(WATCH_URL).text

    assert f'<meta http-equiv="refresh" content="10; url={WATCH_URL}">' in live_page
    assert reverse("rising:stop", args=[run.pk]) in live_page
    assert "Chạy ngay" not in live_page
    assert "Chạy tiếp" not in live_page

    DailyRun.objects.filter(pk=run.pk).update(
        status=Status.SUCCEEDED, step=DailyRun.Step.REPORT, finished_at=at(7, 31)
    )

    done_page = client.get(WATCH_URL).text

    assert 'http-equiv="refresh"' not in done_page
    assert reverse("rising:stop", args=[run.pk]) not in done_page
    assert "Chạy ngay" not in done_page  # hôm nay đã xong: không chạy lại
    assert "Chạy tiếp" not in done_page
    assert "Xong lúc 07:31" in done_page


def test_refused_run_now_never_auto_refreshes(client: Client) -> None:
    # Lượt hôm nay đang chạy thật (vd mở trang trước 7:00, rồi bộ nhịp bắt đầu lượt): "Chạy ngay"
    # bị từ chối ở /rising/run/, nơi chỉ nhận POST → tự tải lại sẽ ra lỗi 405 trống.
    run = today_run()

    response = client.post(RUN_URL)

    assert response.status_code == 409
    assert "đang chạy" in response.text
    assert reverse("rising:stop", args=[run.pk]) in response.text  # vẫn thấy nút Dừng
    assert 'http-equiv="refresh"' not in response.text


def test_report_page_marks_a_stale_run_as_interrupted_and_offers_run_now(client: Client) -> None:
    run = today_run(heartbeat_at=timezone.now() - timedelta(minutes=10))

    page = client.get(WATCH_URL).text

    run.refresh_from_db()
    assert run.status == Status.PAUSED  # xem trang là biết lượt đã chết, như trang lần quét
    assert Button("Chạy tiếp", disabled=False) in buttons(page)
    assert "Chạy ngay" not in page
    assert 'http-equiv="refresh"' not in page


def test_report_empty_state_before_first_run(client: Client) -> None:
    response = client.get(WATCH_URL)

    page = response.text
    assert response.status_code == 200
    assert "Chưa có báo cáo nào" in page
    assert "sau 7:00" in page
    assert Button("Chạy ngay", disabled=False) in buttons(page)
    assert "bấm Chạy ngay" in page
    assert "Chạy tiếp" not in page
    assert 'action="/rising/run/"' in page


@pytest.mark.parametrize(
    "fields",
    [
        {"status": Status.PAUSED},
        {"status": Status.FAILED, "error_message": "Token sai."},
    ],
)
def test_run_now_button_says_continue_when_todays_run_exists(
    client: Client, fields: dict[str, object]
) -> None:
    today_run(heartbeat_at=None, stop_reason=services.REASON_BUSY_APP, **fields)

    for url in (WATCH_URL,):
        page = client.get(url).text

        assert Button("Chạy tiếp", disabled=False) in buttons(page)
        assert "Chạy ngay" not in page  # kể cả trong câu lý do và câu hướng dẫn


def test_empty_state_points_only_at_a_button_that_is_shown(client: Client) -> None:
    run = today_run()  # lượt đầu tiên đang chạy, chưa có báo cáo nào, nút Chạy bị ẩn

    live = client.get(WATCH_URL).text

    assert "Chưa có báo cáo nào" in live
    assert "Chạy ngay" not in live
    assert "Chạy tiếp" not in live
    assert "đang chạy" in live

    DailyRun.objects.filter(pk=run.pk).update(status=Status.PAUSED, heartbeat_at=None)

    paused = client.get(WATCH_URL).text

    assert "Chưa có báo cáo nào" in paused
    assert "bấm Chạy tiếp" in paused


def test_report_page_disables_run_now_while_background_is_busy(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.background.busy_label", lambda: "Lần quét #3")

    page = client.get(WATCH_URL).text

    assert "Lần quét #3" in page
    assert Button("Chạy ngay", disabled=True) in buttons(page)


def test_busy_hint_names_the_button_that_is_shown(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.background.busy_label", lambda: "Lần quét #3")
    today_run(status=Status.PAUSED, heartbeat_at=None)

    page = client.get(WATCH_URL).text

    assert Button("Chạy tiếp", disabled=True) in buttons(page)
    assert "chờ xong rồi bấm Chạy tiếp" in page
    assert "Chạy ngay" not in page


# --- Đường cũ `/rising/` chuyển hướng (F-012) -------------------------------------------------


def test_old_report_url_goes_to_the_rising_tab_keeping_groups_and_gain_sort(
    client: Client,
) -> None:
    response = client.get(
        REPORT_URL, {"audience": "creator", "aspects": "video", "sort": "gain", "min_gain": "9"}
    )

    assert response.status_code == 302
    location = urlsplit(response["Location"])
    assert location.path == "/"
    assert parse_qs(location.query) == {
        "tab": ["rising"],
        "audience": ["creator"],
        "aspects": ["video"],
        "sort": ["gain"],
    }
    assert client.get(REPORT_URL)["Location"] == "/?tab=rising"  # Tiềm năng là mặc định: bỏ


def test_old_report_url_with_a_day_opens_that_run(client: Client) -> None:
    older = make_run(DAY - timedelta(days=1))
    make_run()

    response = client.get(REPORT_URL, {"day": older.day.isoformat(), "max_stars": "500"})

    assert (response.status_code, response["Location"]) == (302, f"{detail(older)}?max_stars=500")


def test_old_report_url_with_a_day_without_report_goes_to_watch(client: Client) -> None:
    make_run()

    response = client.get(REPORT_URL, {"day": "2020-01-01"})

    assert (response.status_code, response["Location"]) == (302, WATCH_URL)


def test_run_detail_needs_a_finished_report(client: Client) -> None:
    running = today_run()

    assert client.get(detail(running)).status_code == 404
    assert client.get(reverse("rising:run_detail", args=[999])).status_code == 404


def test_run_detail_has_no_auto_refresh_or_run_buttons(client: Client) -> None:
    run = make_run()
    today_run()  # lượt hôm nay đang chạy: chỉ trang Theo dõi tự tải lại

    page = client.get(detail(run)).text

    assert 'http-equiv="refresh"' not in page
    assert not [button for button in buttons(page) if button.text in {"Chạy ngay", "Dừng"}]
    assert 'href="/rising/watch/"' in page  # đường quay về Theo dõi


def test_watch_page_summarises_the_latest_report_and_links_every_reported_run(
    client: Client,
) -> None:
    older = make_run(DAY - timedelta(days=1))
    run = make_run()
    DailyRun.objects.filter(pk=run.pk).update(trending_count=12, rising_count=7, unverified_count=3)
    failed = make_run(DAY + timedelta(days=1), status=Status.FAILED, step=DailyRun.Step.VERIFY)

    page = client.get(WATCH_URL).text

    assert "Báo cáo mới nhất: ngày 22/10/2026" in page
    assert re.search(r"<strong>12</strong> repo trending", page)
    assert re.search(r"<strong>7</strong> rising star", page)
    assert 'href="/?tab=rising"' in page
    assert f'href="{detail(run)}"' in page
    assert f'href="{detail(older)}"' in page
    assert f'href="{detail(failed)}"' not in page  # lượt lỗi không có trang chi tiết


# --- Trang Theo dõi --------------------------------------------------------------------------


def test_watch_page_lists_queries_estimate_history_and_buttons(
    client: Client, watch_list: list[WatchQuery]
) -> None:
    yesterday = make_run(timezone.localdate() - timedelta(days=1))
    DailyRun.objects.filter(pk=yesterday.pk).update(
        search_calls_used=500,
        verify_calls_used=300,
        owner_calls_used=37,
        rising_count=14,
        stop_reason="Truy vấn «topic:x» lỗi.\nHết ngân sách xác minh.",
    )
    scan = link_scan(yesterday, WATCHED[0])
    ScanRun.objects.filter(pk=scan.pk).update(api_calls_used=9, fetched_count=250)
    WatchQuery.objects.filter(pk=watch_list[2].pk).update(enabled=False)
    failed = today_run(status=Status.FAILED, error_message="Token sai rồi.", heartbeat_at=None)

    page = client.get(WATCH_URL).text

    for watch in watch_list:
        assert f"<code>{watch.query}</code>" in page
        assert reverse("rising:watch_edit", args=[watch.pk]) in page
    assert "9 lượt gọi" in page  # kết quả lần quét gần nhất
    assert "250 repo" in page
    assert "Tắt" in page
    assert "837 lượt gọi" in page  # ước lượng: 500 + 300 + 37 lượt gọi của lần chạy gần nhất
    assert "Lượt gọi hồ sơ chủ" in page
    assert '<td class="num">37</td>' in page
    assert "Token sai rồi." in page
    assert Button("Chạy tiếp", disabled=False) in buttons(page)  # hôm nay Lỗi → được chạy tiếp
    assert reverse("rising:stop", args=[failed.pk]) not in page
    assert '<td class="num">14</td>' in page  # số rising star trong lịch sử các lượt
    assert '<td class="small">Truy vấn «topic:x» lỗi.<br>Hết ngân sách xác minh.</td>' in page


def test_watch_history_shows_trending_count_and_calls(client: Client) -> None:
    run = make_run(timezone.localdate() - timedelta(days=1))
    DailyRun.objects.filter(pk=run.pk).update(
        trending_count=17, trending_calls_used=123, trending_budget=300
    )

    page = client.get(WATCH_URL).text

    assert '<th class="num">Trending</th>' in page
    assert '<td class="num">17 <span class="muted small">· 123/300 lượt gọi</span></td>' in page


def test_report_stats_show_trending_count(client: Client) -> None:
    run = make_run()
    DailyRun.objects.filter(pk=run.pk).update(trending_count=17)

    page = client.get(detail(run)).text

    assert (
        '<strong>17</strong> repo trending (mọi cỡ) — <a href="/?tab=trending">xem ở Khám phá</a>'
        in page
    )


def test_watch_page_shows_live_run_with_stop_button(client: Client) -> None:
    run = today_run()

    page = client.get(WATCH_URL).text

    assert reverse("rising:stop", args=[run.pk]) in page
    assert "Chạy ngay" not in page
    assert f'<meta http-equiv="refresh" content="10; url={WATCH_URL}">' in page


def test_watch_page_error_after_post_does_not_auto_refresh(client: Client) -> None:
    today_run()  # đang chạy: trang GET sẽ tự tải lại, nhưng trang báo lỗi form thì không

    response = client.post(WATCH_URL, {**WATCH_FORM, "query": "topic:x stars:>5"})

    assert response.status_code == 200
    assert "Không tự ghi `stars:`" in response.text
    assert 'http-equiv="refresh"' not in response.text


def test_watch_page_estimate_without_any_run(client: Client) -> None:
    page = client.get(WATCH_URL).text

    assert "chưa có lần chạy nào" in page


def test_watch_page_warns_when_there_is_no_token(client: Client, settings: Settings) -> None:
    settings.GITHUB_TOKEN = ""

    page = client.get(WATCH_URL).text

    assert "Chưa có GITHUB_TOKEN" in page


def test_watch_add_edit_disable_and_rejects_stars_qualifier(
    client: Client, watch_list: list[WatchQuery]
) -> None:
    # Thêm
    added = client.post(WATCH_URL, WATCH_FORM)

    watch = WatchQuery.objects.get(query="topic:ai-video")
    assert (added.status_code, added["Location"]) == (302, WATCH_URL)
    assert (watch.label, watch.budget, watch.enabled, watch.position) == ("Video AI", 300, True, 5)
    assert "topic:ai-video" in client.get(WATCH_URL).text

    # Truy vấn tự ghi stars: bị từ chối bằng đúng luật của ô Quét
    refused = client.post(WATCH_URL, {**WATCH_FORM, "query": "topic:ai-video stars:>5"})

    assert refused.status_code == 200
    assert "Không tự ghi `stars:`" in refused.text
    assert WatchQuery.objects.count() == len(watch_list) + 1

    # Sửa
    edit_url = reverse("rising:watch_edit", args=[watch.pk])
    form_page = client.get(edit_url).text
    assert 'value="topic:ai-video"' in form_page

    edited = client.post(edit_url, {**WATCH_FORM, "label": "Video & ảnh AI", "max_stars": "800"})

    watch.refresh_from_db()
    assert (edited.status_code, edited["Location"]) == (302, WATCH_URL)
    assert (watch.label, watch.max_stars) == ("Video & ảnh AI", 800)

    # Tắt: bỏ dấu tick "enabled"
    form = {key: value for key, value in WATCH_FORM.items() if key != "enabled"}
    client.post(edit_url, form)

    watch.refresh_from_db()
    assert watch.enabled is False
    assert "Tắt" in client.get(WATCH_URL).text

    # Sửa sai: star tối đa nhỏ hơn tối thiểu
    invalid = client.post(edit_url, {**WATCH_FORM, "min_stars": "100", "max_stars": "50"})

    assert invalid.status_code == 200
    assert "Star tối đa phải lớn hơn hoặc bằng Star tối thiểu." in invalid.text


def test_watch_add_form_proposes_the_next_position(
    client: Client, watch_list: list[WatchQuery]
) -> None:
    page = client.get(WATCH_URL).text

    assert f'name="position" value="{len(watch_list) + 1}"' in page


def test_watch_edit_unknown_id_is_404(client: Client) -> None:
    assert client.get(reverse("rising:watch_edit", args=[999])).status_code == 404
    assert client.post(reverse("rising:watch_edit", args=[999]), WATCH_FORM).status_code == 404


# --- Chạy ngay, Dừng -------------------------------------------------------------------------


def test_run_now_starts_daily_run_in_background(
    client: Client,
    watch_list: list[WatchQuery],
    use_fake: UseFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_fake(some_repos(30))
    labels: list[str] = []

    def record(job: Callable[[int], None], arg: int, *, label: str = "") -> Future[None]:
        labels.append(label)
        job(arg)
        done: Future[None] = Future()
        done.set_result(None)
        return done

    monkeypatch.setattr("core.background.submit_if_idle", record)

    response = client.post(RUN_URL)

    run = DailyRun.objects.get()
    assert (response.status_code, response["Location"]) == (302, WATCH_URL)
    assert labels == [f"Lượt quét hằng ngày {timezone.localdate():%d/%m}"]
    assert (run.day, run.status) == (timezone.localdate(), Status.SUCCEEDED)  # chạy tại chỗ ở test
    assert run.scans.count() == len(watch_list)


def test_run_now_continues_a_paused_run(
    client: Client, watch_list: list[WatchQuery], use_fake: UseFake
) -> None:
    use_fake(some_repos(30))
    paused = today_run(status=Status.PAUSED, heartbeat_at=None, pause_kind="stopped")

    response = client.post(RUN_URL)

    paused.refresh_from_db()
    assert response.status_code == 302
    assert paused.status == Status.SUCCEEDED
    assert DailyRun.objects.count() == 1


def test_run_now_409_when_busy_or_done_today(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.background.busy_label", lambda: "Lần quét #7")

    busy = client.post(RUN_URL)

    assert busy.status_code == 409
    assert "Lần quét #7" in busy.text
    assert DailyRun.objects.count() == 0

    monkeypatch.setattr("core.background.busy_label", lambda: None)
    make_run(timezone.localdate())

    done = client.post(RUN_URL)

    assert done.status_code == 409
    assert "Hôm nay đã quét xong" in done.text
    assert DailyRun.objects.count() == 1


def test_run_now_409_while_a_scan_is_live(client: Client) -> None:
    scan = ScanRun.objects.create(
        query="topic:x", status=ScanRun.Status.RUNNING, heartbeat_at=timezone.now()
    )

    response = client.post(RUN_URL)

    assert response.status_code == 409
    assert f"lần quét #{scan.pk}" in response.text
    assert DailyRun.objects.count() == 0


def test_run_now_releases_the_run_when_the_background_thread_gets_taken(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.background.submit_if_idle", lambda *args, **kwargs: None)

    response = client.post(RUN_URL)

    run = DailyRun.objects.get()
    assert response.status_code == 409
    assert (run.status, run.stop_reason) == (Status.PAUSED, services.REASON_BUSY_APP)
    assert services.REASON_BUSY_APP in response.text


def test_run_now_requires_post(client: Client) -> None:
    assert client.get(RUN_URL).status_code == 405


def test_stop_requests_daily_stop(client: Client) -> None:
    run = today_run()

    response = client.post(reverse("rising:stop", args=[run.pk]))

    run.refresh_from_db()
    assert (response.status_code, response["Location"]) == (302, WATCH_URL)
    assert run.stop_requested is True


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        ({"next": "watch"}, WATCH_URL),
        ({"next": "report"}, WATCH_URL),
        ({}, WATCH_URL),
        ({"next": "https://evil.example/"}, WATCH_URL),  # không bao giờ đi theo `next`
        ({"next": "//evil.example"}, WATCH_URL),
    ],
)
def test_stop_always_returns_to_the_watch_page(
    client: Client, form: dict[str, str], expected: str
) -> None:
    run = today_run()

    response = client.post(reverse("rising:stop", args=[run.pk]), form)

    run.refresh_from_db()
    assert (response.status_code, response["Location"]) == (302, expected)
    assert run.stop_requested is True


def test_stop_unknown_run_is_404_and_get_is_refused(client: Client) -> None:
    assert client.post(reverse("rising:stop", args=[999])).status_code == 404
    assert client.get(reverse("rising:stop", args=[1])).status_code == 405


# --- Thanh điều hướng ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "current"),
    [
        ("/", "Khám phá"),
        ("/scan/", "Quét"),
        ("/scans/{scan}/", "Quét"),
        ("/rising/runs/{run}/", "Theo dõi"),
        ("/rising/watch/", "Theo dõi"),
        ("/rising/watch/{watch}/", "Theo dõi"),
    ],
)
def test_nav_links_on_every_page(
    client: Client, watch_list: list[WatchQuery], path: str, current: str
) -> None:
    scan = ScanRun.objects.create(query="topic:x", status=ScanRun.Status.SUCCEEDED)
    url = path.format(scan=scan.pk, run=make_run().pk, watch=watch_list[0].pk)

    page = client.get(url).text

    links = nav_links(page)
    assert [(link.href, link.text) for link in links] == [
        ("/", "Khám phá"),
        ("/scan/", "Quét"),
        ("/rising/watch/", "Theo dõi"),
    ]
    assert [link.text for link in links if link.current] == [current]


def test_nav_marks_watch_on_the_refused_run_now_page(client: Client) -> None:
    make_run(timezone.localdate())

    page = client.post(RUN_URL).text

    assert [link.text for link in nav_links(page) if link.current] == ["Theo dõi"]


def test_nav_ignores_a_same_named_view_of_another_namespace() -> None:
    # Chỉ namespace "rising" đánh dấu "Theo dõi"; view `watch` của app khác thì không.
    request = RequestFactory().get("/khac/watch/")
    request.resolver_match = ResolverMatch(
        lambda request: None, (), {}, url_name="watch", app_names=["khac"], namespaces=["khac"]
    )

    page = render_to_string("base.html", request=request)

    links = nav_links(page)
    assert len(links) == 3
    assert not [link for link in links if link.current]


def test_repository_links_have_no_unsafe_markup(client: Client) -> None:
    # Dữ liệu từ GitHub không bao giờ được chèn thô vào trang (tên, mô tả, ngôn ngữ).
    run = make_run()
    repo = make_repo(1)
    Repository.objects.filter(pk=repo.pk).update(language="<i>Py</i>")
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)

    page = client.get(detail(run)).text

    assert "<i>Py</i>" not in page
    assert "&lt;i&gt;Py&lt;/i&gt;" in page


# --- Điểm và repo nghi star giả trên trang Rising star (F-006) --------------------------------


def test_report_page_shows_scores_and_hides_high_suspicion_with_reasons(client: Client) -> None:
    run = make_run()
    created = DAY - timedelta(days=30)
    make_repo(
        1,
        created=created,
        stars=613,
        forks=2,
        pushed_at=timezone.make_aware(datetime.combine(created, time(18))),
    )
    make_check(run, 1, stars=613, gain_7d=300, is_rising=True)
    make_repo(2, stars=1000, forks=4)  # "Cần xem": 4 fork trên 1.000 star
    make_check(run, 2, stars=900, gain_7d=60, is_rising=True)
    make_check(run, 3, stars=300, gain_7d=100, is_rising=True)
    DailyRun.objects.filter(pk=run.pk).update(rising_count=3)

    page = client.get(detail(run)).text

    for header in ("Tiềm năng", "Chất lượng", "Nghi star giả"):
        assert f'<th class="num">{header}</th>' in page
    assert "Phổ biến <strong>" in page  # bấm vào điểm thì thấy thành phần
    assert "3</strong> rising star (đã ẩn 1 nghi star giả)" in page
    main, hidden = page.split("Đã ẩn 1 repo nghi star giả — Hiện")
    assert "gia-lap/repo-1" not in main
    assert "gia-lap/repo-1" in hidden
    assert "2 fork trên 613 star (dưới 0,5%)" in hidden
    assert "không có commit nào sau ngày tạo" in hidden
    assert "Cần xem" in main
    assert "4 fork trên 1.000 star (dưới 0,5%)" in main


def test_report_page_without_hidden_rows_has_no_hidden_section(client: Client) -> None:
    run = make_run()
    make_check(run, 3, stars=300, gain_7d=100, is_rising=True)

    page = client.get(detail(run)).text

    assert "nghi star giả — Hiện" not in page
    assert "đã ẩn" not in page


def test_report_sort_choice_switches_order_and_is_kept_in_form(client: Client) -> None:
    run = make_run()
    make_check(run, 1, stars=999, gain_7d=60, is_rising=True)  # Tiềm năng thấp, tăng nhiều
    make_check(run, 2, stars=60, gain_7d=55, is_rising=True)  # Tiềm năng cao, tăng ít

    default = client.get(detail(run)).text
    by_gain = client.get(detail(run), {"sort": "gain"}).text

    assert default.index("gia-lap/repo-2") < default.index("gia-lap/repo-1")
    assert by_gain.index("gia-lap/repo-1") < by_gain.index("gia-lap/repo-2")
    assert '<option value="gain" selected>' in by_gain
    assert '<option value="potential" selected>' in default


def test_report_unverified_rows_show_estimated_potential(client: Client) -> None:
    run = make_run()
    make_check(run, 1, stars=300, gain_7d=30, source=Source.SNAPSHOT)

    page = client.get(detail(run)).text

    assert "Tiềm năng (ước lượng)" in page
    assert "<strong>36</strong>" in page


def test_report_page_shows_labels_and_filters_by_group(client: Client) -> None:
    run = make_run()
    for github_id in (1, 2):
        make_check(run, github_id, stars=300, gain_7d=100 + github_id, is_rising=True)
    label_repository(make_repo(1), audience=("creator",), aspects=("video",))

    every = client.get(detail(run)).text
    creators = client.get(detail(run), {"audience": "creator"}).text

    assert "Video &amp; làm phim AI" in every
    assert 'href="/?tab=all&amp;aspects=video"' in every
    assert "gia-lap/repo-2" in every
    assert "gia-lap/repo-1" in creators
    assert "gia-lap/repo-2" not in creators
    assert 'value="creator" checked' in creators


# --- Chia trang (trang mặc định nhẹ, tự tải lại không nặng) -----------------------------------


def pager_links(page: str, anchor: str) -> list[dict[str, list[str]]]:
    """Tham số của các link chuyển trang dẫn tới `#anchor`, đã bỏ escape HTML."""
    hrefs = re.findall(r'href="([^"]*#' + anchor + ')"', page)
    return [parse_qs(urlsplit(html.unescape(href)).query) for href in hrefs]


def test_report_pager_keeps_every_filter_and_the_other_section_page(client: Client) -> None:
    run = make_run()
    for github_id in range(1, services.RISING_PAGE_SIZE + 2):
        make_check(run, github_id, stars=300, gain_7d=100 + github_id, is_rising=True)
        label_repository(make_repo(github_id), audience=("creator",))
    query = {
        "max_stars": "500",
        "min_gain": "10",
        "sort": "gain",
        "audience": "creator",
        "upage": "3",
    }

    first = client.get(detail(run), query).text
    second = client.get(detail(run), {**query, "page": "2"}).text

    [next_link] = pager_links(first, "rising")
    assert next_link == {**{key: [value] for key, value in query.items()}, "page": ["2"]}
    assert f"Bảng rising star ({services.RISING_PAGE_SIZE + 1})" in first
    assert "Trang 1/2" in first
    assert "gia-lap/repo-1<" not in first  # tăng ít nhất → trang 2
    assert "gia-lap/repo-1<" in second
    assert f'<td class="num">{services.RISING_PAGE_SIZE + 1}</td>' in second  # đánh số tiếp
    [previous_link] = pager_links(second, "rising")
    assert previous_link["page"] == ["1"]


def test_report_filter_form_starts_again_from_first_page(client: Client) -> None:
    run = make_run()
    make_check(run, 1, stars=300, gain_7d=100, is_rising=True)

    page = client.get(detail(run), {"page": "2", "upage": "2"}).text

    assert 'name="page"' not in page  # bấm Lọc → về trang 1 của cả hai mục
    assert 'name="upage"' not in page
    assert "Trang 1/1" not in page  # chỉ một trang thì không hiện thanh chuyển trang


def test_report_unverified_section_is_collapsed_until_paged(client: Client) -> None:
    run = make_run()
    for github_id in range(1, services.UNVERIFIED_PAGE_SIZE + 2):
        make_check(run, github_id, stars=300, gain_7d=github_id, source=Source.SNAPSHOT)

    default = client.get(detail(run)).text
    paged = client.get(detail(run), {"upage": "2"}).text

    assert f"Ứng viên chưa xác minh ({services.UNVERIFIED_PAGE_SIZE + 1})" in default
    assert '<details class="unverified-list">' in default
    assert "gia-lap/repo-1<" not in default  # ước lượng tăng ít nhất → trang 2
    assert '<details class="unverified-list" open>' in paged
    assert "gia-lap/repo-1<" in paged
    [next_link] = pager_links(default, "unverified")
    assert next_link == {"upage": ["2"]}


def test_report_with_invalid_page_falls_back_to_first_page(client: Client) -> None:
    run = make_run()
    make_check(run, 1, stars=300, gain_7d=100, is_rising=True)

    response = client.get(detail(run), {"page": "abc", "upage": "-1"})

    assert response.status_code == 200
    assert "gia-lap/repo-1<" in response.text
