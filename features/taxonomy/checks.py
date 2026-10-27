"""Kiểm `categories.toml` khi chạy `manage.py check` / mở app: file hỏng thì báo ngay."""

import tomllib
from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.core.checks import CheckMessage, Error, register

from features.taxonomy import categories


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
