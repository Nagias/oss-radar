"""Dữ liệu dùng chung cho mọi trang: danh sách góc nhìn ở thanh bên (F-012, QĐ-23).

Lớp mỏng: đọc bộ lọc của trang Khám phá (nếu đang ở đó) rồi gọi `services`. Không có nghiệp vụ.
"""

from typing import Any

from django.http import HttpRequest

from features.browse import services
from features.browse.forms import BrowseForm


def sidebar(request: HttpRequest) -> dict[str, Any]:
    match = getattr(request, "resolver_match", None)
    current = None
    if match is not None and match.view_name == "browse:explore":
        current = BrowseForm(request.GET or None).filters()
    return {"saved_views": services.saved_views(current)}
