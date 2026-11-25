"""Trang Theo dõi và trang chi tiết lượt — lớp mỏng: nhận yêu cầu → gọi services → hiển thị."""

from typing import Any

from django.http import Http404, HttpRequest, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core import background
from features.rising import growth, services
from features.rising.forms import ReportFilterForm, WatchQueryForm
from features.rising.models import DailyRun, WatchQuery
from features.taxonomy.services import load_taxonomy


@require_GET
def report(request: HttpRequest) -> HttpResponse:
    """Đường cũ `/rising/` (trước F-012): chuyển tạm (302) sang trang mới.

    - Có `?day=` và ngày đó có báo cáo → trang chi tiết lượt, giữ các ô lọc khác.
    - Có `?day=` mà ngày đó không có báo cáo → trang Theo dõi (bảng các lượt gần đây).
    - Không có ngày → tab Đang lên của trang Khám phá, giữ nhóm và cách sắp "Tăng 7 ngày".
    """
    form = ReportFilterForm(request.GET or None)
    _max_stars, _min_gain, day = form.values()
    if day is not None:
        run = services.report_run_for(day)
        if run is None:
            return redirect("rising:watch")
        params = request.GET.copy()
        params.pop("day", None)
        return redirect(_with_query(reverse("rising:run_detail", args=[run.pk]), params))
    audience, aspects = form.groups()
    params = QueryDict(mutable=True)
    params["tab"] = "rising"
    params.setlist("audience", list(audience))
    params.setlist("aspects", list(aspects))
    if form.sort_order() == services.SORT_GAIN:
        params["sort"] = services.SORT_GAIN
    return redirect(_with_query(reverse("browse:explore"), params))


@require_GET
def run_detail(request: HttpRequest, run_id: int) -> HttpResponse:
    run = services.reported_run(run_id)
    if run is None:
        raise Http404("Lượt này chưa lập xong báo cáo")
    return render(request, "rising/run_detail.html", _report_context(request.GET, run))


@require_http_methods(["GET", "POST"])
def watch(request: HttpRequest) -> HttpResponse:
    services.pause_stale_daily_runs()
    if request.method == "POST":
        form = WatchQueryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("rising:watch")
    else:
        form = WatchQueryForm(initial={"position": services.next_watch_position()})
    # Trang trả về sau POST (form báo lỗi) không tự tải lại: tải lại bằng GET sẽ mất chữ đã nhập.
    refresh_url = request.get_full_path() if request.method == "GET" else None
    return render(request, "rising/watch.html", _watch_context(form, refresh_url=refresh_url))


@require_http_methods(["GET", "POST"])
def watch_edit(request: HttpRequest, watch_id: int) -> HttpResponse:
    watch_query = get_object_or_404(WatchQuery, pk=watch_id)
    if request.method == "POST":
        form = WatchQueryForm(request.POST, instance=watch_query)
        if form.is_valid():
            form.save()
            return redirect("rising:watch")
    else:
        form = WatchQueryForm(instance=watch_query)
    return render(request, "rising/watch_edit.html", {"watch": watch_query, "form": form})


@require_POST
def run_now(request: HttpRequest) -> HttpResponse:
    busy = background.busy_label()
    if busy is not None:
        return _refuse_run_now(request, _busy_message(busy))
    try:
        run = services.prepare_daily_run()
    except services.DailyRunBlockedError as exc:
        return _refuse_run_now(request, str(exc))
    queued = background.submit_if_idle(
        services.execute_daily_run, run.pk, label=f"Lượt quét hằng ngày {run.day:%d/%m}"
    )
    if queued is None:
        # Luồng nền vừa bị việc khác chiếm: không để lượt "đang chạy" nằm chờ rồi bị coi là bỏ dở.
        services.release_unstarted_daily_run(run)
        return _refuse_run_now(request, run.stop_reason)
    return redirect("rising:watch")


@require_POST
def stop(request: HttpRequest, run_id: int) -> HttpResponse:
    run = get_object_or_404(DailyRun, pk=run_id)
    services.request_daily_stop(run)
    return redirect("rising:watch")


def _report_context(query: QueryDict, run: DailyRun) -> dict[str, Any]:
    form = ReportFilterForm(query or None)
    max_stars, min_gain, _day = form.values()
    sort = form.sort_order()
    audience, aspects = form.groups()
    page, unverified_page = form.pages()
    report = services.daily_report(
        run,
        max_stars=max_stars,
        min_gain=min_gain,
        sort=sort,
        audience=audience,
        aspects=aspects,
        page=page,
        unverified_page=unverified_page,
    )
    return {
        "form": form,
        "report": report,
        "rising_pager": _pager(query, "page", report.rising_page),
        "unverified_pager": _pager(query, "upage", report.unverified_page),
        # Mục chưa xác minh gập sẵn (đỡ rối mắt); đang lật trang của nó thì mở sẵn.
        "unverified_open": "upage" in query,
        "is_latest": services.latest_report_run() == run,
        "max_stars": max_stars,
        "min_gain": min_gain,
        "sort": sort,
        "taxonomy": load_taxonomy(),
        "selected_audience": audience,
        "selected_aspects": aspects,
        "candidate_min": growth.CANDIDATE_MIN_ESTIMATE_7D,
    }


def _pager(query: QueryDict, name: str, info: services.PageInfo) -> dict[str, Any] | None:
    """Thanh chuyển trang của một mục; `None` khi chỉ có một trang."""
    if info.pages <= 1:
        return None
    return {
        "info": info,
        "previous_url": _page_url(query, name, info.page - 1) if info.page > 1 else None,
        "next_url": _page_url(query, name, info.page + 1) if info.page < info.pages else None,
    }


def _page_url(query: QueryDict, name: str, page: int) -> str:
    """Địa chỉ trang `page` của một mục, giữ nguyên mọi ô lọc và trang đang xem của mục kia."""
    params = query.copy()
    params[name] = str(page)
    return f"?{params.urlencode()}"


def _with_query(path: str, params: QueryDict) -> str:
    return f"{path}?{params.urlencode()}" if params else path


def _watch_context(
    form: WatchQueryForm, *, refresh_url: str | None, run_error: str | None = None
) -> dict[str, Any]:
    status = services.today_status()
    return {
        "status": status,
        "latest_report": services.latest_report_run(),
        "rows": services.watch_overview(),
        "estimate": services.daily_estimate(),
        "verify_budget_anonymous": services.VERIFY_BUDGET_ANONYMOUS,
        "runs": services.recent_daily_runs(),
        "form": form,
        "run_error": run_error,
        "refresh_url": refresh_url if status.is_live else None,
        "busy_label": background.busy_label(),
    }


def _refuse_run_now(request: HttpRequest, message: str) -> HttpResponse:
    """Không chạy được: hiện lại trang Theo dõi kèm lý do (trạng thái 409), không tự tải lại.

    Trang từ chối nằm ở /rising/run/ (chỉ nhận POST): tự tải lại ở đây sẽ ra lỗi 405 trống.
    """
    form = WatchQueryForm(initial={"position": services.next_watch_position()})
    context = _watch_context(form, refresh_url=None, run_error=message)
    return render(request, "rising/watch.html", context, status=409)


def _busy_message(label: str) -> str:
    return f"App đang chạy việc nền: {label} — chờ xong, hoặc dừng việc đó rồi thử lại."
