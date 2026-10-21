"""Lính gác quy tắc dự án: biến luật trong CLAUDE.md thành test, quên luật là CI đỏ."""

import re
from pathlib import Path

import httpx
import pytest
from respx.models import AllMockedAssertionError

ROOT = Path(__file__).resolve().parents[1]
CODE_DIRS = ("config", "features", "integrations", "templates", "static", "tests")
CODE_SUFFIXES = {".py", ".html", ".css", ".js", ".txt"}
DEBT_MARKER = re.compile(r"DEBT\((D-\d{3})\)")
DEBT_ROW = re.compile(r"^\|\s*(D-\d{3})\s*\|[^|]*\|\s*([^|]+?)\s*\|", re.MULTILINE)
OPEN_STATUS = "Mở"


def _code_files() -> list[Path]:
    files = [ROOT / "manage.py", ROOT / "conftest.py"]
    for folder in CODE_DIRS:
        base = ROOT / folder
        if base.is_dir():
            files.extend(p for p in base.rglob("*") if p.suffix in CODE_SUFFIXES and p.is_file())
    return files


def _debt_ledger() -> dict[str, str]:
    text = (ROOT / "DEBT.md").read_text(encoding="utf-8")
    rows = DEBT_ROW.findall(text)
    ids = [debt_id for debt_id, _ in rows]
    duplicated = sorted({debt_id for debt_id in ids if ids.count(debt_id) > 1})
    assert not duplicated, f"DEBT.md có mã nợ trùng: {duplicated}"
    return dict(rows)


def _package_dirs(parent: str) -> list[str]:
    base = ROOT / parent
    return sorted(p.name for p in base.iterdir() if (p / "__init__.py").is_file())


def test_debt_markers_in_code_are_registered_and_open() -> None:
    ledger = _debt_ledger()
    problems: list[str] = []
    for path in _code_files():
        for debt_id in DEBT_MARKER.findall(path.read_text(encoding="utf-8")):
            where = path.relative_to(ROOT).as_posix()
            if debt_id not in ledger:
                problems.append(f"{where}: {debt_id} chưa có trong DEBT.md")
            elif ledger[debt_id] != OPEN_STATUS:
                status = ledger[debt_id]
                problems.append(f"{where}: {debt_id} đã '{status}' mà dấu nợ vẫn còn trong code")
    assert not problems, "\n".join(problems)


def test_every_debt_row_has_a_detail_section() -> None:
    text = (ROOT / "DEBT.md").read_text(encoding="utf-8")
    missing = [debt_id for debt_id in _debt_ledger() if f"### {debt_id} " not in text]
    assert not missing, f"DEBT.md thiếu mục chi tiết cho: {missing}"


def test_templates_have_no_todo_comments() -> None:
    # Ruff đã chặn TODO/FIXME trong .py; template HTML thì kiểm ở đây.
    pattern = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in _code_files()
        if path.suffix != ".py" and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"Ghi đường tắt vào DEBT.md thay vì TODO/FIXME: {offenders}"


@pytest.mark.parametrize("parent", ["features", "integrations"])
def test_every_module_folder_is_a_python_package(parent: str) -> None:
    # Thiếu __init__.py thì pytest coi thư mục tests/ bên trong là gói "tests" riêng → import sai.
    missing = [
        path.name
        for path in sorted((ROOT / parent).iterdir())
        if path.is_dir() and path.name != "__pycache__" and not (path / "__init__.py").is_file()
    ]
    assert not missing, f"Thiếu __init__.py trong {parent}/: {missing}"


@pytest.mark.parametrize("parent", ["features", "integrations"])
def test_feature_map_lists_every_module(parent: str) -> None:
    feature_map = (ROOT / "FEATURE_MAP.md").read_text(encoding="utf-8")
    missing = [name for name in _package_dirs(parent) if f"`{parent}/{name}/`" not in feature_map]
    assert not missing, f"FEATURE_MAP.md chưa có mục cho {parent}/: {missing}"


@pytest.mark.parametrize("parent", ["features", "integrations"])
def test_every_module_has_its_own_tests(parent: str) -> None:
    missing = [
        name
        for name in _package_dirs(parent)
        if not (ROOT / parent / name / "tests" / "__init__.py").is_file()
    ]
    assert not missing, f"Thiếu thư mục tests/ (có __init__.py) trong {parent}/: {missing}"


def test_real_http_is_blocked_in_normal_tests() -> None:
    # Lưới an toàn: test thường không bao giờ lọt request ra Internet.
    with pytest.raises(AllMockedAssertionError):
        httpx.get("https://example.com/")
