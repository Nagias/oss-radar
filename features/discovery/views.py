"""Trang web của tính năng Quét — lớp mỏng: nhận yêu cầu → gọi services → hiển thị."""

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core import background
from features.discovery import services
from features.discovery.forms import ResumeForm, ScanForm
from features.discovery.models import ScanRun

# DEBT(D-007): trang kết quả chỉ hiện 500 repo nhiều star nhất; xem đủ cần trang duyệt kho.
RESULTS_SHOWN_LIMIT = 500


@require_http_methods(["GET", "POST"])
def home(request: HttpRequest) -> HttpResponse:
    services.pause_stale_scans()
    form = ScanForm(request.POST or None)
    busy = background.busy_label()
    if request.method == "POST" and busy is not None:
        form.add_error(None, _busy_message(busy))
    elif request.method == "POST" and form.is_valid():
        try:
            scan = services.start_scan(form.to_request())
        except services.ScanAlreadyRunningError as exc:
            form.add_error(None, _already_running_message(exc))
        else:
            _run_in_background(scan)
            return redirect("discovery:scan_detail", scan_id=scan.pk)
    context = {
        "form": form,
        "recent_scans": services.recent_scans(),
        "live_scan": services.live_scan(),
        "busy_label": busy,
    }
    return render(request, "discovery/home.html", context)


@require_GET
def scan_detail(request: HttpRequest, scan_id: int) -> HttpResponse:
    services.pause_stale_scans()
    scan = get_object_or_404(ScanRun, pk=scan_id)
    return render(request, "discovery/scan_detail.html", _detail_context(scan))


@require_POST
def scan_stop(request: HttpRequest, scan_id: int) -> HttpResponse:
    scan = get_object_or_404(ScanRun, pk=scan_id)
    services.request_stop(scan)
    return redirect("discovery:scan_detail", scan_id=scan.pk)


@require_POST
def scan_resume(request: HttpRequest, scan_id: int) -> HttpResponse:
    scan = get_object_or_404(ScanRun, pk=scan_id)
    form = ResumeForm(request.POST)
    busy = background.busy_label()
    if busy is not None:
        form.add_error(None, _busy_message(busy))
    elif form.is_valid():
        extra = form.cleaned_data["extra_budget"]
        try:
            services.resume_scan(scan, extra_budget=extra)
        except services.ScanAlreadyRunningError as exc:
            form.add_error(None, _already_running_message(exc))
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            _run_in_background(scan, refund_budget=extra)
            return redirect("discovery:scan_detail", scan_id=scan.pk)
    context = _detail_context(scan, resume_form=form)
    return render(request, "discovery/scan_detail.html", context, status=409)


def _detail_context(scan: ScanRun, *, resume_form: ResumeForm | None = None) -> dict[str, Any]:
    if resume_form is None and scan.can_resume:
        resume_form = ResumeForm()
    return {
        "scan": scan,
        "scored": services.scored_results(scan, limit=RESULTS_SHOWN_LIMIT),
        "results_limit": RESULTS_SHOWN_LIMIT,
        "problems": services.problem_slices(scan),
        "progress": services.slice_progress(scan),
        "resume_form": resume_form,
        "auto_refresh": scan.is_live,
        "busy_label": background.busy_label(),
    }


def _run_in_background(scan: ScanRun, *, refund_budget: int = 0) -> None:
    """Xếp lần quét vào luồng nền nếu nó còn rảnh; vừa bị việc khác chiếm thì nhả lần quét ra."""
    queued = background.submit_if_idle(services.execute_scan, scan.pk, label=f"Lần quét #{scan.pk}")
    if queued is None:
        services.release_unstarted_scan(scan, refund_budget=refund_budget)


def _already_running_message(exc: services.ScanAlreadyRunningError) -> str:
    return f"Đang chạy lần quét #{exc.scan.pk} — chờ nó xong hoặc bấm Dừng ở lần đó."


def _busy_message(label: str) -> str:
    return f"App đang chạy việc nền: {label} — chờ xong, hoặc dừng việc đó rồi thử lại."
