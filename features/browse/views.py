"""Trang Kho repo — lớp mỏng: nhận bộ lọc → gọi services → hiển thị."""

from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import render
from django.views.decorators.http import require_GET

from features.browse import services
from features.browse.forms import BrowseForm
from features.taxonomy.services import load_taxonomy


@require_GET
def repos(request: HttpRequest) -> HttpResponse:
    form = BrowseForm(request.GET or None)
    filters = form.filters()
    page = services.browse(filters)
    taxonomy = load_taxonomy()
    context = {
        "form": form,
        "filters": filters,
        "page": page,
        "audience": [(c, page.counts.get(c.code, 0)) for c in taxonomy.audience],
        "aspects": [(c, page.counts.get(c.code, 0)) for c in taxonomy.aspects],
        "unclassified_count": page.counts.get(services.UNCLASSIFIED, 0),
        "sorts": services.SORTS,
        "previous_url": _page_url(request.GET, page.page - 1) if page.page > 1 else None,
        "next_url": _page_url(request.GET, page.page + 1) if page.page < page.pages else None,
    }
    return render(request, "browse/repos.html", context)


def _page_url(query: QueryDict, page: int) -> str:
    """Địa chỉ trang `page` giữ nguyên mọi ô lọc đang chọn."""
    params = query.copy()
    params["page"] = str(page)
    return f"?{params.urlencode()}"
