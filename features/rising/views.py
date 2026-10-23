"""Trang Rising star và trang Theo dõi — lớp mỏng: nhận yêu cầu → gọi services → hiển thị."""

from typing import Any

from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core import background
from features.rising import growth, services
from features.rising.forms import ReportFilterForm, WatchQueryForm
from features.rising.models import DailyRun, WatchQuery

# Trang mà nút Dừng được bấm từ đó → nơi quay về. Chỉ nhận tên trong danh sách này.
_STOP_RETURNS = {"report": "rising:report", "watch": "rising:watch"}


@require_GET
def report(request: HttpRequest) -> HttpResponse:
    services.pause_stale_daily_runs()
    context = _report_context(request.GET, refresh_url=request.get_full_path())
    return render(request, "rising/report.html", context)


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
    return redirect("rising:report")


@require_POST
def stop(request: HttpRequest, run_id: int) -> HttpResponse:
    run = get_object_or_404(DailyRun, pk=run_id)
    services.request_daily_stop(run)
    return redirect(_STOP_RETURNS.get(request.POST.get("next", ""), "rising:report"))


def _report_context(
    query: QueryDict, *, refresh_url: str | None = None, run_error: str | None = None
) -> dict[str, Any]:
    """`refresh_url`: nơi trang tự tải lại khi lượt đang chạy; `None` = không tự tải lại.

    Trang từ chối "Chạy ngay" nằm ở /rising/run/ (chỉ nhận POST) nên không được truyền URL nào.
    """
    status = services.today_status()
    form = ReportFilterForm(query or None)
    max_stars, min_gain, day = form.values()
    sort = form.sort_order()
    run = services.report_run_for(day) if day is not None else services.latest_report_run()
    return {
        "status": status,
        "form": form,
        "report": None
        if run is None
        else services.daily_report(run, max_stars=max_stars, min_gain=min_gain, sort=sort),
        "days": services.report_days(),
        "selected_day": day,
        "missing_day": day if run is None else None,
        "max_stars": max_stars,
        "min_gain": min_gain,
        "sort": sort,
        "candidate_min": growth.CANDIDATE_MIN_ESTIMATE_7D,
        "run_error": run_error,
        "refresh_url": refresh_url if status.is_live else None,
        "busy_label": background.busy_label(),
    }


def _watch_context(form: WatchQueryForm, *, refresh_url: str | None) -> dict[str, Any]:
    status = services.today_status()
    return {
        "status": status,
        "rows": services.watch_overview(),
        "estimate": services.daily_estimate(),
        "verify_budget_anonymous": services.VERIFY_BUDGET_ANONYMOUS,
        "runs": services.recent_daily_runs(),
        "form": form,
        "run_error": None,
        "refresh_url": refresh_url if status.is_live else None,
        "busy_label": background.busy_label(),
    }


def _refuse_run_now(request: HttpRequest, message: str) -> HttpResponse:
    """Không chạy được: hiện lại trang báo cáo kèm lý do (trạng thái 409)."""
    context = _report_context(QueryDict(), run_error=message)
    return render(request, "rising/report.html", context, status=409)


def _busy_message(label: str) -> str:
    return f"App đang chạy việc nền: {label} — chờ xong, hoặc dừng việc đó rồi thử lại."
