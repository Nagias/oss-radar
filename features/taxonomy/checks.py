"""Kiểm `categories.toml`, `keywords.toml` khi chạy `manage.py check` / mở app: hỏng thì báo."""

import tomllib
from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.core.checks import CheckMessage, Error, register

from features.taxonomy import categories, keywords


@register()
def check_taxonomy(app_configs: Sequence[AppConfig] | None, **kwargs: Any) -> list[CheckMessage]:
    try:
        categories.load_taxonomy()
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        return [
            Error(
                f"Bộ nhóm {categories.CATEGORIES_PATH.name} không đọc được: {exc}",
                hint="Sửa file theo hướng dẫn ở đầu file, rồi tăng `version`.",
                id="taxonomy.E001",
            )
        ]
    return []


@register()
def check_keywords(app_configs: Sequence[AppConfig] | None, **kwargs: Any) -> list[CheckMessage]:
    try:
        categories.load_taxonomy()
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return []  # bộ nhóm hỏng đã được `check_taxonomy` báo (E001)
    try:
        keywords.load_keywords()
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        return [
            Error(
                f"Bộ từ khoá {keywords.KEYWORDS_PATH.name} không đọc được: {exc}",
                hint="Sửa file theo hướng dẫn ở đầu file, rồi tăng `version`.",
                id="taxonomy.E002",
            )
        ]
    return []
