"""Trang web của tính năng Quét — lớp mỏng: nhận yêu cầu → gọi services → hiển thị."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from features.discovery import services
from features.discovery.forms import ScanForm
from features.discovery.models import ScanRun


@require_http_methods(["GET", "POST"])
def home(request: HttpRequest) -> HttpResponse:
    form = ScanForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        scan = services.run_scan(form.cleaned_data["query"])
        return redirect("discovery:scan_detail", scan_id=scan.pk)
    context = {"form": form, "recent_scans": services.recent_scans()}
    return render(request, "discovery/home.html", context)


@require_GET
def scan_detail(request: HttpRequest, scan_id: int) -> HttpResponse:
    scan = get_object_or_404(ScanRun, pk=scan_id)
    context = {"scan": scan, "results": services.scan_results(scan)}
    return render(request, "discovery/scan_detail.html", context)
