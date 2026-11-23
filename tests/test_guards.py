"""Lính gác quy tắc dự án: biến luật trong CLAUDE.md thành test, quên luật là CI đỏ."""

import re
from pathlib import Path

import httpx
import pytest
from respx.models import AllMockedAssertionError

ROOT = Path(__file__).resolve().parents[1]
CODE_DIRS = ("config", "core", "features", "integrations", "templates", "static", "tests")
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


def test_feature_map_lists_shared_core() -> None:
    feature_map = (ROOT / "FEATURE_MAP.md").read_text(encoding="utf-8")
    assert "`core/`" in feature_map, "FEATURE_MAP.md chưa có mục cho hạ tầng dùng chung `core/`"


def test_core_has_its_own_tests() -> None:
    assert (ROOT / "core" / "tests" / "__init__.py").is_file(), "Thiếu core/tests/__init__.py"


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


FONT_DIR = ROOT / "static" / "fonts" / "be-vietnam-pro"
FONT_WEIGHTS = ("400", "500", "600", "700")
FONT_SUBSETS = ("latin", "latin-ext", "vietnamese")
NETWORK_ASSET = re.compile(
    r"<(?:script|link|img|iframe|source)\b[^>]*\b(?:src|href)\s*=\s*[\"']?(?:https?:)?//"
    r"|url\(\s*[\"']?(?:https?:)?//"
    r"|@import",
    re.IGNORECASE,
)


def test_static_assets_never_load_from_the_network() -> None:
    # App chạy local: trang không được kéo script, CSS, phông, ảnh từ máy chủ ngoài (QĐ-20).
    # Link <a href="https://github.com/…"> tới repo thì vẫn được phép.
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in _code_files()
        if path.suffix in {".html", ".css", ".js"}
        and NETWORK_ASSET.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"Tài nguyên tải từ mạng (phải đóng gói trong static/): {offenders}"


def test_bundled_font_has_license_and_all_subsets() -> None:
    license_text = (FONT_DIR / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL Open Font License" in license_text
    css = (ROOT / "static" / "css" / "fonts.css").read_text(encoding="utf-8")
    blocks = re.findall(r"@font-face\s*\{([^}]*)\}", css)
    assert len(blocks) == len(FONT_WEIGHTS) * len(FONT_SUBSETS)
    declared = set()
    for block in blocks:
        weight = re.search(r"font-weight:\s*(\d+)", block)
        source = re.search(r'url\("\.\./fonts/be-vietnam-pro/([^"]+)"\)', block)
        assert weight, block
        assert source, block
        assert "unicode-range" in block
        assert "font-display: swap" in block
        assert (FONT_DIR / source.group(1)).is_file(), f"Thiếu file phông {source.group(1)}"
        declared.add(source.group(1))
        assert source.group(1).startswith(f"be-vietnam-pro-{weight.group(1)}-")
    expected = {f"be-vietnam-pro-{w}-{s}.woff2" for w in FONT_WEIGHTS for s in FONT_SUBSETS}
    assert declared == expected


APP_JS_MAX_LINES = 150


def test_app_js_stays_small() -> None:
    # JS chỉ tăng cường dần, không có test tự động (D-010): giữ nhỏ để đọc là hiểu hết.
    lines = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= APP_JS_MAX_LINES, (
        f"app.js dài {len(lines)} dòng (tối đa {APP_JS_MAX_LINES})"
    )
