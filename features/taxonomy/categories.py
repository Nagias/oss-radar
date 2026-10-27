"""Bộ nhóm phân loại: đọc `categories.toml` và kiểm chặt (file do người sửa tay, dễ gõ nhầm)."""

import functools
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

CATEGORIES_PATH = Path(__file__).with_name("categories.toml")
OTHER = "khac"  # nhóm bắt buộc của lớp "Làm được gì": repo không hợp nhóm nào

Axis = Literal["audience", "aspects"]
AXES: tuple[Axis, ...] = ("audience", "aspects")
_CODE = re.compile(r"[a-z][a-z_]*")


@dataclass(frozen=True, slots=True)
class Category:
    code: str
    name: str
    hint: str


@dataclass(frozen=True, slots=True)
class Taxonomy:
    version: int
    audience: tuple[Category, ...]
    aspects: tuple[Category, ...]

    def of(self, axis: Axis) -> tuple[Category, ...]:
        return self.audience if axis == "audience" else self.aspects

    def codes(self, axis: Axis) -> frozenset[str]:
        return frozenset(category.code for category in self.of(axis))

    def name_of(self, code: str) -> str | None:
        """Tên hiển thị của một mã; mã không còn trong bộ nhóm (đã bỏ) thì None."""
        for category in (*self.audience, *self.aspects):
            if category.code == code:
                return category.name
        return None

    def category(self, code: str) -> Category | None:
        for category in (*self.audience, *self.aspects):
            if category.code == code:
                return category
        return None


@functools.cache
def load_taxonomy() -> Taxonomy:
    """Bộ nhóm hiện hành (đọc file một lần cho cả tiến trình)."""
    with CATEGORIES_PATH.open("rb") as file:
        data = tomllib.load(file)
    return parse_taxonomy(data)


def parse_taxonomy(data: dict[str, Any]) -> Taxonomy:
    """Đổi dữ liệu file thành `Taxonomy`; sai chỗ nào thì `ValueError` nói rõ chỗ đó."""
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(f"`version` phải là số nguyên từ 1, đang là {version!r}")
    seen: set[str] = set()
    audience = _parse_axis(data, "audience", seen)
    aspects = _parse_axis(data, "aspects", seen)
    if OTHER not in {category.code for category in aspects}:
        raise ValueError(f"lớp `aspects` phải có nhóm `{OTHER}` (Khác)")
    return Taxonomy(version=version, audience=audience, aspects=aspects)


def _parse_axis(data: dict[str, Any], axis: Axis, seen: set[str]) -> tuple[Category, ...]:
    raw = data.get(axis)
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"lớp `{axis}` phải có ít nhất một nhóm")
    categories: list[Category] = []
    for index, item in enumerate(raw, start=1):
        where = f"nhóm thứ {index} của lớp `{axis}`"
        if not isinstance(item, dict):
            raise ValueError(f"{where} phải là bảng [[{axis}]]")
        code, name, hint = item.get("code"), item.get("name"), item.get("hint")
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise ValueError(f"{where}: mã {code!r} chỉ được gồm chữ thường a-z và dấu gạch dưới")
        if code in seen:
            raise ValueError(f"{where}: mã `{code}` bị trùng")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{where} (`{code}`): thiếu tên hiển thị")
        if not isinstance(hint, str) or not hint.strip():
            raise ValueError(f"{where} (`{code}`): thiếu `hint` (câu gợi ý cho AI)")
        seen.add(code)
        categories.append(Category(code=code, name=name.strip(), hint=hint.strip()))
    return tuple(categories)
