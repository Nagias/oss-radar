"""Bộ từ khoá của luật phân loại: file thật đọc được, file hỏng thì báo lỗi rõ (taxonomy.E002)."""

from pathlib import Path
from typing import Any

import pytest

from features.taxonomy import checks, keywords
from features.taxonomy.categories import OTHER, load_taxonomy
from features.taxonomy.keywords import load_keywords, parse_keywords


def test_real_file_covers_every_group() -> None:
    taxonomy = load_taxonomy()
    loaded = load_keywords()

    assert loaded.version >= 1
    assert set(loaded.aspects) == taxonomy.codes("aspects") - {OTHER}
    assert set(loaded.audience) == taxonomy.codes("audience")
    assert "comfyui" in loaded.aspects["image"].strong
    # Nhóm suy ra: mã "Dành cho ai" → các mã "Làm được gì".
    assert set(loaded.derived) <= taxonomy.codes("audience")
    assert "video" in loaded.derived["creator"]


def valid() -> dict[str, Any]:
    taxonomy = load_taxonomy()
    return {
        "version": 3,
        "derived": {"creator": ["video"]},
        "aspects": {
            code: {"strong": [f"{code}-manh"], "weak": [f"{code}-yeu"]}
            for code in taxonomy.codes("aspects") - {OTHER}
        },
        "audience": {
            code: {"strong": [f"{code}-manh"], "weak": []} for code in taxonomy.codes("audience")
        },
    }


def test_parse_valid_data() -> None:
    parsed = parse_keywords(valid(), load_taxonomy())

    assert parsed.version == 3
    assert parsed.aspects["video"].strong == ("video-manh",)
    assert parsed.aspects["video"].weak == ("video-yeu",)
    assert parsed.audience["creator"].weak == ()
    assert parsed.derived == {"creator": ("video",)}


def _broken(change: str) -> dict[str, Any]:
    data = valid()
    if change == "version":
        data["version"] = 0
    elif change == "unknown aspect":
        data["aspects"]["la_hoac"] = {"strong": ["x"], "weak": []}
    elif change == "khac":
        data["aspects"][OTHER] = {"strong": ["x"], "weak": []}
    elif change == "missing group":
        del data["aspects"]["video"]
    elif change == "missing audience":
        del data["audience"]["creator"]
    elif change == "uppercase":
        data["aspects"]["video"]["strong"] = ["Video"]
    elif change == "empty keyword":
        data["aspects"]["video"]["weak"] = [" "]
    elif change == "not a list":
        data["aspects"]["video"]["strong"] = "video"
    elif change == "strong and weak":
        data["aspects"]["video"]["weak"] = ["video-manh"]
    elif change == "duplicate":
        data["aspects"]["video"]["strong"] = ["a", "a"]
    elif change == "derived unknown audience":
        data["derived"]["ai_do"] = ["video"]
    elif change == "derived unknown aspect":
        data["derived"]["creator"] = ["la_hoac"]
    elif change == "no keywords at all":
        data["aspects"]["video"] = {"strong": [], "weak": []}
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("version", "version"),
        ("unknown aspect", "la_hoac"),
        ("khac", "khac"),
        ("missing group", "video"),
        ("missing audience", "creator"),
        ("uppercase", "chữ thường"),
        ("empty keyword", "rỗng"),
        ("not a list", "danh sách"),
        ("strong and weak", "video-manh"),
        ("duplicate", "trùng"),
        ("derived unknown audience", "ai_do"),
        ("derived unknown aspect", "la_hoac"),
        ("no keywords at all", "video"),
    ],
)
def test_parse_rejects_broken_data(change: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_keywords(_broken(change), load_taxonomy())


def test_check_passes_with_real_file() -> None:
    assert checks.check_keywords(None) == []


def test_check_reports_broken_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = tmp_path / "keywords.toml"
    broken.write_text("version = 0\n", encoding="utf-8")
    monkeypatch.setattr(keywords, "KEYWORDS_PATH", broken)
    load_keywords.cache_clear()
    try:
        errors = checks.check_keywords(None)
    finally:
        load_keywords.cache_clear()

    assert [error.id for error in errors] == ["taxonomy.E002"]
    assert "keywords.toml" in errors[0].msg
