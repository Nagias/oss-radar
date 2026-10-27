"""Trang Rising star và trang Theo dõi — lớp mỏng: nhận yêu cầu → gọi services → hiển thị."""

import re
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, time, timedelta

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

pytestmark = pytest.mark.django_db

Status = DailyRun.Status
Source = RisingCheck.Source
REPORT_URL = reverse("rising:report")
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


def link_scan(run: DailyRun, query: str, *, position: int = 1) -> ScanRun:
    scan = ScanRun.objects.create(
        query=query, origin=ScanRun.Origin.DAILY, status=ScanRun.Status.SUCCEEDED
    )
    watch = WatchQuery.objects.filter(query=query).first()
    DailyRunScan.objects.create(daily_run=run, watch_query=watch, scan_run=scan, position=position)
    return scan


# --- Trang Rising star -----------------------------------------------------------------------


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

    page = client.get(REPORT_URL).text

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

    page = client.get(REPORT_URL).text

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

    page = client.get(REPORT_URL).text

    assert "Truy vấn «topic:x» lỗi: mạng." in page
    assert "Xong nhưng còn sót" in page


def test_report_filters_from_query_string(client: Client) -> None:
    older = make_run(DAY - timedelta(days=1))
    make_check(older, 9, stars=100, gain_7d=70, is_rising=True)
    run = make_run()
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)
    make_check(run, 2, stars=900, gain_7d=60, is_rising=True)
    make_check(run, 3, stars=1500, gain_7d=40)

    default = client.get(REPORT_URL).text
    narrow = client.get(REPORT_URL, {"max_stars": "500", "min_gain": "100"}).text
    wide = client.get(REPORT_URL, {"max_stars": "2000", "min_gain": "0"}).text
    other_day = client.get(REPORT_URL, {"day": older.day.isoformat()}).text

    assert [name in default for name in ("repo-1<", "repo-2<", "repo-3<")] == [True, True, False]
    assert [name in narrow for name in ("repo-1<", "repo-2<", "repo-3<")] == [True, False, False]
    assert [name in wide for name in ("repo-1<", "repo-2<", "repo-3<")] == [True, True, True]
    assert "repo-9<" in other_day
    assert "repo-1<" not in other_day
    assert 'value="500"' in narrow  # ô lọc giữ giá trị vừa chọn
    assert f'<option value="{older.day.isoformat()}" selected>' in other_day


def test_report_with_invalid_filter_shows_error_and_falls_back_to_defaults(
    client: Client,
) -> None:
    run = make_run()
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)

    page = client.get(REPORT_URL, {"min_gain": "-5", "max_stars": "abc"}).text

    assert 'class="error"' in page
    assert "repo-1<" in page  # vẫn hiện báo cáo theo ngưỡng mặc định


def test_report_keeps_a_valid_day_when_another_filter_is_invalid(client: Client) -> None:
    older = make_run(DAY - timedelta(days=1))
    make_check(older, 9, stars=100, gain_7d=70, is_rising=True)
    make_check(older, 8, stars=900, gain_7d=60, is_rising=True)
    make_run()
    day = older.day.isoformat()

    bad_gain = client.get(REPORT_URL, {"day": day, "min_gain": "-5", "max_stars": "500"}).text
    bad_day = client.get(REPORT_URL, {"day": "hôm qua", "max_stars": "500", "min_gain": "65"}).text

    assert 'class="error"' in bad_gain
    assert f'<option value="{day}" selected>' in bad_gain  # vẫn đúng ngày đã chọn
    assert "repo-9<" in bad_gain  # ngưỡng tăng sai → mặc định 50; ngưỡng star 500 hợp lệ vẫn giữ
    assert "repo-8<" not in bad_gain  # 900 star: trên ngưỡng 500 của ô hợp lệ
    assert 'class="error"' in bad_day
    assert "repo-9<" not in bad_day  # ngày sai → báo cáo mới nhất (không có repo-9)


def test_report_for_a_day_without_report_says_so(client: Client) -> None:
    make_run()

    response = client.get(REPORT_URL, {"day": "2020-01-01"})

    assert response.status_code == 200
    assert "Chưa có báo cáo cho ngày 01/01/2020" in response.text


def test_report_auto_refresh_only_while_live(client: Client) -> None:
    make_run(DAY - timedelta(days=1))
    run = today_run(step=DailyRun.Step.VERIFY)

    live_page = client.get(REPORT_URL).text

    assert f'<meta http-equiv="refresh" content="10; url={REPORT_URL}">' in live_page
    assert reverse("rising:stop", args=[run.pk]) in live_page
    assert "Chạy ngay" not in live_page
    assert "Chạy tiếp" not in live_page

    DailyRun.objects.filter(pk=run.pk).update(
        status=Status.SUCCEEDED, step=DailyRun.Step.REPORT, finished_at=at(7, 31)
    )

    done_page = client.get(REPORT_URL).text

    assert 'http-equiv="refresh"' not in done_page
    assert reverse("rising:stop", args=[run.pk]) not in done_page
    assert "Chạy ngay" not in done_page  # hôm nay đã xong: không chạy lại
    assert "Chạy tiếp" not in done_page
    assert "Xong lúc 07:31" in done_page


def test_report_refresh_target_keeps_the_current_filter(client: Client) -> None:
    today_run()

    page = client.get(REPORT_URL, {"max_stars": "500", "min_gain": "100"}).text

    # `&` trong thuộc tính HTML phải viết `&amp;`; trình duyệt đọc lại thành `&`.
    assert (
        f'<meta http-equiv="refresh" content="10; url={REPORT_URL}?max_stars=500&amp;min_gain=100">'
        in page
    )


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

    page = client.get(REPORT_URL).text

    run.refresh_from_db()
    assert run.status == Status.PAUSED  # xem trang là biết lượt đã chết, như trang lần quét
    assert ">Chạy tiếp</button>" in page
    assert "Chạy ngay" not in page
    assert 'http-equiv="refresh"' not in page


def test_report_empty_state_before_first_run(client: Client) -> None:
    response = client.get(REPORT_URL)

    page = response.text
    assert response.status_code == 200
    assert "Chưa có báo cáo nào" in page
    assert "sau 7:00" in page
    assert ">Chạy ngay</button>" in page
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

    for url in (REPORT_URL, WATCH_URL):
        page = client.get(url).text

        assert ">Chạy tiếp</button>" in page
        assert "Chạy ngay" not in page  # kể cả trong câu lý do và câu hướng dẫn


def test_empty_state_points_only_at_a_button_that_is_shown(client: Client) -> None:
    run = today_run()  # lượt đầu tiên đang chạy, chưa có báo cáo nào, nút Chạy bị ẩn

    live = client.get(REPORT_URL).text

    assert "Chưa có báo cáo nào" in live
    assert "Chạy ngay" not in live
    assert "Chạy tiếp" not in live
    assert "đang chạy" in live

    DailyRun.objects.filter(pk=run.pk).update(status=Status.PAUSED, heartbeat_at=None)

    paused = client.get(REPORT_URL).text

    assert "Chưa có báo cáo nào" in paused
    assert "bấm Chạy tiếp" in paused


def test_report_page_disables_run_now_while_background_is_busy(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.background.busy_label", lambda: "Lần quét #3")

    page = client.get(REPORT_URL).text

    assert "Lần quét #3" in page
    assert re.search(r"<button[^>]*disabled[^>]*>Chạy ngay", page)


def test_busy_hint_names_the_button_that_is_shown(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.background.busy_label", lambda: "Lần quét #3")
    today_run(status=Status.PAUSED, heartbeat_at=None)

    page = client.get(REPORT_URL).text

    assert re.search(r"<button[^>]*disabled[^>]*>Chạy tiếp", page)
    assert "chờ xong rồi bấm Chạy tiếp" in page
    assert "Chạy ngay" not in page


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
    assert ">Chạy tiếp</button>" in page  # hôm nay Lỗi → được chạy tiếp
    assert reverse("rising:stop", args=[failed.pk]) not in page
    assert '<td class="num">14</td>' in page  # số rising star trong lịch sử các lượt
    assert '<td class="small">Truy vấn «topic:x» lỗi.<br>Hết ngân sách xác minh.</td>' in page


def test_watch_page_shows_live_run_with_stop_button(client: Client) -> None:
    run = today_run()

    page = client.get(WATCH_URL).text

    assert reverse("rising:stop", args=[run.pk]) in page
    assert "Chạy ngay" not in page
    assert f'<meta http-equiv="refresh" content="10; url={WATCH_URL}">' in page
    assert 'name="next" value="watch"' in page


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
    assert (response.status_code, response["Location"]) == (302, REPORT_URL)
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
    assert (response.status_code, response["Location"]) == (302, REPORT_URL)
    assert run.stop_requested is True


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        ({"next": "watch"}, WATCH_URL),
        ({"next": "report"}, REPORT_URL),
        ({}, REPORT_URL),
        ({"next": "https://evil.example/"}, REPORT_URL),  # chỉ nhận tên trong danh sách cho phép
        ({"next": "//evil.example"}, REPORT_URL),
    ],
)
def test_stop_returns_to_the_page_it_was_pressed_on(
    client: Client, form: dict[str, str], expected: str
) -> None:
    run = today_run()

    response = client.post(reverse("rising:stop", args=[run.pk]), form)

    run.refresh_from_db()
    assert (response.status_code, response["Location"]) == (302, expected)
    assert run.stop_requested is True


def test_stop_buttons_remember_which_page_they_are_on(client: Client) -> None:
    today_run()

    assert 'name="next" value="report"' in client.get(REPORT_URL).text
    assert 'name="next" value="watch"' in client.get(WATCH_URL).text


def test_stop_unknown_run_is_404_and_get_is_refused(client: Client) -> None:
    assert client.post(reverse("rising:stop", args=[999])).status_code == 404
    assert client.get(reverse("rising:stop", args=[1])).status_code == 405


# --- Thanh điều hướng ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "current"),
    [
        ("/", "Quét"),
        ("/scans/{scan}/", "Quét"),
        ("/rising/", "Rising star"),
        ("/rising/watch/", "Theo dõi"),
        ("/rising/watch/{watch}/", "Theo dõi"),
        ("/repos/", "Kho repo"),
    ],
)
def test_nav_links_on_every_page(
    client: Client, watch_list: list[WatchQuery], path: str, current: str
) -> None:
    scan = ScanRun.objects.create(query="topic:x", status=ScanRun.Status.SUCCEEDED)
    url = path.format(scan=scan.pk, watch=watch_list[0].pk)

    page = client.get(url).text

    links = re.findall(r'<a href="([^"]+)"( aria-current="page")?>([^<]+)</a>', _nav(page))
    assert [(href, label) for href, _, label in links] == [
        ("/", "Quét"),
        ("/rising/", "Rising star"),
        ("/repos/", "Kho repo"),
        ("/rising/watch/", "Theo dõi"),
    ]
    assert [label for _, mark, label in links if mark] == [current]


def test_nav_marks_rising_star_on_the_refused_run_now_page(client: Client) -> None:
    make_run(timezone.localdate())

    page = client.post(RUN_URL).text

    assert 'aria-current="page">Rising star<' in page


def test_nav_ignores_a_same_named_view_of_another_namespace() -> None:
    # Chỉ "rising:watch" (có namespace) đánh dấu "Theo dõi"; view `watch` của app khác thì không.
    request = RequestFactory().get("/khac/watch/")
    request.resolver_match = ResolverMatch(
        lambda request: None, (), {}, url_name="watch", app_names=["khac"], namespaces=["khac"]
    )

    page = render_to_string("base.html", request=request)

    assert 'aria-current="page"' not in _nav(page)


def _nav(page: str) -> str:
    start = page.index('<nav class="site-nav"')
    return page[start : page.index("</nav>", start)]


def test_repository_links_have_no_unsafe_markup(client: Client) -> None:
    # Dữ liệu từ GitHub không bao giờ được chèn thô vào trang (tên, mô tả, ngôn ngữ).
    run = make_run()
    repo = make_repo(1)
    Repository.objects.filter(pk=repo.pk).update(language="<i>Py</i>")
    make_check(run, 1, stars=340, gain_7d=120, is_rising=True)

    page = client.get(REPORT_URL).text

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

    page = client.get(REPORT_URL).text

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

    page = client.get(REPORT_URL).text

    assert "nghi star giả — Hiện" not in page
    assert "đã ẩn" not in page


def test_report_sort_choice_switches_order_and_is_kept_in_form(client: Client) -> None:
    run = make_run()
    make_check(run, 1, stars=999, gain_7d=60, is_rising=True)  # Tiềm năng thấp, tăng nhiều
    make_check(run, 2, stars=60, gain_7d=55, is_rising=True)  # Tiềm năng cao, tăng ít

    default = client.get(REPORT_URL).text
    by_gain = client.get(REPORT_URL, {"sort": "gain"}).text

    assert default.index("gia-lap/repo-2") < default.index("gia-lap/repo-1")
    assert by_gain.index("gia-lap/repo-1") < by_gain.index("gia-lap/repo-2")
    assert '<option value="gain" selected>' in by_gain
    assert '<option value="potential" selected>' in default


def test_report_unverified_rows_show_estimated_potential(client: Client) -> None:
    run = make_run()
    make_check(run, 1, stars=300, gain_7d=30, source=Source.SNAPSHOT)

    page = client.get(REPORT_URL).text

    assert "Tiềm năng (ước lượng)" in page
    assert "<strong>36</strong>" in page


def test_report_page_shows_labels_and_filters_by_group(client: Client) -> None:
    run = make_run()
    for github_id in (1, 2):
        make_check(run, github_id, stars=300, gain_7d=100 + github_id, is_rising=True)
    label_repository(make_repo(1), audience=("creator",), aspects=("video",))

    every = client.get(REPORT_URL).text
    creators = client.get(REPORT_URL, {"audience": "creator"}).text

    assert "Video &amp; làm phim AI" in every
    assert 'href="/repos/?aspects=video"' in every
    assert "gia-lap/repo-2" in every
    assert "gia-lap/repo-1" in creators
    assert "gia-lap/repo-2" not in creators
    assert 'value="creator" checked' in creators
