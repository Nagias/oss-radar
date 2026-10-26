"""Bộ nhóm đọc từ file cấu hình: đúng thiết kế F-010 mục 4, file hỏng thì báo lỗi rõ."""

from pathlib import Path
from typing import Any

import pytest

from features.taxonomy import categories, checks
from features.taxonomy.categories import Taxonomy, load_taxonomy, parse_taxonomy

AUDIENCE = ["developer", "marketer", "business", "creator", "gamedev", "research"]
ASPECTS = [
    "agent",
    "video",
    "image",
    "audio",
    "writing",
    "social",
    "ads",
    "scraping",
    "devtools",
    "ai_infra",
    "webapp",
    "game",
    "commerce",
    "productivity",
    "khac",
]


def test_real_file_matches_design() -> None:
    taxonomy = load_taxonomy()

    assert taxonomy.version >= 1
    assert [c.code for c in taxonomy.audience] == AUDIENCE
    assert [c.code for c in taxonomy.aspects] == ASPECTS
    assert taxonomy.name_of("creator") == "Nhà sáng tạo nội dung (video, YouTube, ảnh)"
    assert taxonomy.name_of("video") == "Video & làm phim AI"
    assert all(c.hint.strip() for c in (*taxonomy.audience, *taxonomy.aspects))
    assert taxonomy.codes("audience") == frozenset(AUDIENCE)
    assert taxonomy.codes("aspects") == frozenset(ASPECTS)


def test_unknown_code_has_no_name() -> None:
    assert load_taxonomy().name_of("da_bo") is None


def valid() -> dict[str, Any]:
    return {
        "version": 2,
        "audience": [{"code": "developer", "name": "Lập trình viên", "hint": "viết code"}],
        "aspects": [
            {"code": "video", "name": "Video", "hint": "làm video"},
            {"code": "khac", "name": "Khác", "hint": "không thuộc nhóm nào"},
        ],
    }


def test_parse_valid_data() -> None:
    taxonomy = parse_taxonomy(valid())

    assert isinstance(taxonomy, Taxonomy)
    assert taxonomy.version == 2
    assert taxonomy.codes("aspects") == frozenset({"video", "khac"})


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.pop("version"), "version"),
        (lambda d: d.update(version=0), "version"),
        (lambda d: d.update(audience=[]), "audience"),
        (lambda d: d["aspects"].append(dict(d["aspects"][0])), "trùng"),
        (lambda d: d["audience"][0].update(code="Dev Tool"), "mã"),
        (lambda d: d["audience"][0].update(name="  "), "tên"),
        (lambda d: d["aspects"].pop(), "khac"),
        (lambda d: d["audience"].append({"code": "video", "name": "x", "hint": "y"}), "trùng"),
        (lambda d: d["aspects"][0].pop("hint"), "hint"),
    ],
)
def test_parse_rejects_broken_data(change: Any, message: str) -> None:
    data = valid()
    change(data)

    with pytest.raises(ValueError, match=message):
        parse_taxonomy(data)


def test_check_reports_broken_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = tmp_path / "categories.toml"
    broken.write_text('version = 1\n[[audience]]\ncode = "x"\n', encoding="utf-8")
    monkeypatch.setattr(categories, "CATEGORIES_PATH", broken)
    load_taxonomy.cache_clear()

    try:
        errors = checks.check_taxonomy(None)
    finally:
        load_taxonomy.cache_clear()

    assert [error.id for error in errors] == ["taxonomy.E001"]
    assert "categories.toml" in errors[0].msg


def test_check_passes_on_real_file() -> None:
    assert checks.check_taxonomy(None) == []
