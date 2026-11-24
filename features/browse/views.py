"""Trang Khám phá — lớp mỏng: nhận bộ lọc → gọi services → hiển thị."""

from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from features.browse import services
from features.browse.filters import SORT_LABELS, TAB_SORTS
from features.browse.forms import BrowseForm, SavedViewForm
from features.browse.models import SavedView
from features.rising import services as rising
from features.taxonomy.services import load_taxonomy


@require_GET
def repos(request: HttpRequest) -> HttpResponse:
    """Đường cũ `/repos/` (trước F-012): chuyển tạm (302) sang Khám phá, giữ mọi ô lọc.

    Ô "Chỉ rising star" / "Chỉ trending" cũ thành tab Đang lên / Trending; còn lại là tab Toàn kho.
    """
    params = request.GET.copy()
    rising_only = params.pop("rising_only", None)
    trending_only = params.pop("trending_only", None)
    params.pop("tab", None)
    tab = "trending" if trending_only else "rising" if rising_only else "all"
    query = QueryDict(mutable=True)
    query["tab"] = tab
    for key, values in params.lists():
        query.setlist(key, values)
    return redirect(f"{reverse('browse:explore')}?{query.urlencode()}")


@require_GET
def explore(request: HttpRequest) -> HttpResponse:
    form = BrowseForm(request.GET or None)
    filters = form.filters()
    page = services.explore(filters)
    taxonomy = load_taxonomy()
    context = {
        "form": form,
        "filters": filters,
        "page": page,
        "tabs": services.tab_links(filters),
        "sorts": {key: SORT_LABELS[key] for key in TAB_SORTS[filters.tab]},
        "chips": services.active_chips(filters),
        "filters_open": services.has_more_filters(filters),
        "save": services.save_state(filters),
        "clear_url": services.clear_url(filters),
        "show_suspicious_url": services.show_suspicious_url(filters),
        "is_live": rising.today_status().is_live,
        "audience": [(c, page.counts.get(c.code, 0)) for c in taxonomy.audience],
        "aspects": [(c, page.counts.get(c.code, 0)) for c in taxonomy.aspects],
        "unclassified_count": page.counts.get(services.UNCLASSIFIED, 0),
        "previous_url": services.page_url(filters, page.page - 1) if page.page > 1 else None,
        "next_url": services.page_url(filters, page.page + 1) if page.page < page.pages else None,
    }
    return render(request, "browse/explore.html", context)


@require_http_methods(["GET", "POST"])
def views_page(request: HttpRequest) -> HttpResponse:
    """Trang quản lý góc nhìn; POST = lưu góc nhìn mới (từ trang Khám phá) rồi mở nó."""
    if request.method == "POST":
        form = SavedViewForm(request.POST)
        if form.is_valid():
            view = services.save_view(form.cleaned_data["name"], form.cleaned_data["query"])
            return redirect(services.view_url(view))
        return _render_views(request, form, status=400)
    return _render_views(request, None)


@require_POST
def view_edit(request: HttpRequest, view_id: int) -> HttpResponse:
    """Đổi tên (gửi `name`) hoặc thay bộ lọc (gửi `query`) của một góc nhìn."""
    view = get_object_or_404(SavedView, pk=view_id)
    data = {
        "name": request.POST.get("name", view.name),
        "query": request.POST.get("query", view.query),
    }
    form = SavedViewForm(data, instance=view)
    if not form.is_valid():
        return _render_views(request, form, status=400)
    services.update_view(view, name=form.cleaned_data["name"], query=form.cleaned_data["query"])
    if "query" in request.POST:
        return redirect(services.view_url(view))
    return redirect("browse:views")


@require_POST
def view_delete(request: HttpRequest, view_id: int) -> HttpResponse:
    view = get_object_or_404(SavedView, pk=view_id)
    services.delete_view(view)
    return redirect("browse:views")


def _render_views(
    request: HttpRequest, form: SavedViewForm | None, *, status: int = 200
) -> HttpResponse:
    context = {"items": services.saved_views(), "form": form}
    return render(request, "browse/views.html", context, status=status)
