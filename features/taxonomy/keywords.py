"""Bộ từ khoá của luật phân loại: đọc `keywords.toml` và kiểm chặt (file do người sửa tay).

Tách khỏi `categories.toml` có chủ đích: `version` ở đây chỉ nói "luật đã đổi", không làm nhãn do AI
gắn bị coi là cũ (thiết kế bộ luật 2026-11-28, mục "Gói 1a / 1b").
"""

import functools
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from features.taxonomy.categories import OTHER, Axis, Taxonomy, load_taxonomy

KEYWORDS_PATH = Path(__file__).with_name("keywords.toml")


@dataclass(frozen=True, slots=True)
class GroupKeywords:
    strong: tuple[str, ...]  # một từ là đủ xếp vào nhóm
    weak: tuple[str, ...]  # phải có từ thứ hai mới tính


@dataclass(frozen=True, slots=True)
class Keywords:
    version: int
    aspects: Mapping[str, GroupKeywords]
    audience: Mapping[str, GroupKeywords]
    derived: Mapping[str, tuple[str, ...]]  # mã "Dành cho ai" → các mã "Làm được gì" suy ra nó


@functools.cache
def load_keywords() -> Keywords:
    """Bộ từ khoá hiện hành (đọc file một lần cho cả tiến trình)."""
    with KEYWORDS_PATH.open("rb") as file:
        data = tomllib.load(file)
    return parse_keywords(data, load_taxonomy())


def parse_keywords(data: dict[str, Any], taxonomy: Taxonomy) -> Keywords:
    """Đổi dữ liệu file thành `Keywords`; sai chỗ nào thì `ValueError` nói rõ chỗ đó."""
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(f"`version` phải là số nguyên từ 1, đang là {version!r}")
    aspects = _parse_axis(data, "aspects", taxonomy.codes("aspects") - {OTHER})
    audience = _parse_axis(data, "audience", taxonomy.codes("audience"))
    return Keywords(
        version=version,
        aspects=aspects,
        audience=audience,
        derived=_parse_derived(data.get("derived", {}), taxonomy),
    )


def _parse_axis(
    data: dict[str, Any], axis: Axis, expected: frozenset[str]
) -> dict[str, GroupKeywords]:
    raw = data.get(axis)
    if not isinstance(raw, dict):
        raise ValueError(f"thiếu bảng `[{axis}.<mã nhóm>]`")
    unknown = sorted(set(raw) - expected)
    if unknown:
        raise ValueError(f"lớp `{axis}`: mã `{unknown[0]}` không có trong bộ nhóm (hoặc là `khac`)")
    missing = sorted(expected - set(raw))
    if missing:
        raise ValueError(f"lớp `{axis}`: nhóm `{missing[0]}` chưa có từ khoá")
    groups: dict[str, GroupKeywords] = {}
    for code, item in raw.items():
        where = f"`[{axis}.{code}]`"
        if not isinstance(item, dict):
            raise ValueError(f"{where} phải là bảng có `strong` và `weak`")
        strong = _parse_words(item.get("strong", []), f"{where} strong")
        weak = _parse_words(item.get("weak", []), f"{where} weak")
        both = sorted(set(strong) & set(weak))
        if both:
            raise ValueError(f"{where}: từ `{both[0]}` nằm ở cả strong và weak")
        if not strong and not weak:
            raise ValueError(f"{where}: nhóm `{code}` chưa có từ khoá nào")
        groups[code] = GroupKeywords(strong=strong, weak=weak)
    return groups


def _parse_words(raw: object, where: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{where} phải là danh sách từ khoá")
    words: list[str] = []
    for word in raw:
        if not isinstance(word, str) or not word.strip():
            raise ValueError(f"{where}: có từ khoá rỗng")
        if word != word.strip().lower():
            raise ValueError(f"{where}: từ `{word}` phải viết chữ thường, không thừa dấu cách")
        if word in words:
            raise ValueError(f"{where}: từ `{word}` bị trùng")
        words.append(word)
    return tuple(words)


def _parse_derived(raw: object, taxonomy: Taxonomy) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict):
        raise ValueError("`[derived]` phải là bảng: mã Dành cho ai = [các mã Làm được gì]")
    derived: dict[str, tuple[str, ...]] = {}
    for audience, aspects in raw.items():
        if audience not in taxonomy.codes("audience"):
            raise ValueError(f"`[derived]`: `{audience}` không phải mã của lớp audience")
        if not isinstance(aspects, list) or not aspects:
            raise ValueError(f"`[derived]` {audience}: phải là danh sách mã của lớp aspects")
        for code in aspects:
            if code not in taxonomy.codes("aspects") or code == OTHER:
                raise ValueError(f"`[derived]` {audience}: `{code}` không phải mã của lớp aspects")
        derived[audience] = tuple(aspects)
    return derived
