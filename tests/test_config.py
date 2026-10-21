"""Cấu hình dự án: giá trị sai phải báo lỗi rõ ràng ngay khi khởi động, không chạy âm thầm."""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command

from config.settings import parse_bool, resolve_secret_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("TRUE", True), ("1", True), ("on", True), ("false", False), ("0", False)],
)
def test_parse_bool_reads_common_spellings(raw: str, expected: bool) -> None:
    assert parse_bool(raw, name="X", default=not expected) is expected


@pytest.mark.parametrize("raw", ["", "   "])
def test_parse_bool_blank_falls_back_to_default(raw: str) -> None:
    assert parse_bool(raw, name="X", default=True) is True
    assert parse_bool(raw, name="X", default=False) is False


def test_parse_bool_rejects_typo_instead_of_guessing() -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_DEBUG"):
        parse_bool("ture", name="DJANGO_DEBUG", default=True)


def test_secret_key_is_required_when_debug_is_off() -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        resolve_secret_key("", debug=False)


def test_secret_key_given_is_used_as_is() -> None:
    assert resolve_secret_key("  khoa-rieng  ", debug=False) == "khoa-rieng"


def test_secret_key_is_random_in_debug_when_blank() -> None:
    first = resolve_secret_key("", debug=True)
    second = resolve_secret_key("", debug=True)
    assert len(first) >= 50
    assert first != second


def test_django_system_check_passes() -> None:
    # Nạp toàn bộ cấu hình, bảng đường dẫn, template — sai ở đâu là đỏ ở đây.
    call_command("check", fail_level="WARNING")
