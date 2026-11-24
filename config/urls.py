"""Bảng đường dẫn gốc: mỗi tính năng gắn urls.py của nó vào đây bằng include()."""

from django.urls import URLPattern, URLResolver, include, path

urlpatterns: list[URLPattern | URLResolver] = [
    # Khám phá ở trang chủ `/` (F-012); Quét ở `/scan/`, lần quét ở `/scans/<id>/`.
    path("", include("features.browse.urls")),
    path("", include("features.discovery.urls")),
    path("rising/", include("features.rising.urls")),
]
