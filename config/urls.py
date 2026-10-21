"""Bảng đường dẫn gốc: mỗi tính năng gắn urls.py của nó vào đây bằng include()."""

from django.urls import URLPattern, URLResolver

urlpatterns: list[URLPattern | URLResolver] = []
