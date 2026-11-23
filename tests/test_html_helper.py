"""Bộ đọc HTML cho test: đọc đúng ý nghĩa (link, nút, form), không phụ thuộc thứ tự thuộc tính."""

from tests.html import Button, NavLink, buttons, forms, nav_links

PAGE = """
<nav aria-label="Khác"><a href="/x/">Không lấy</a></nav>
<aside>
  <nav class="sidebar-nav" aria-label="Các trang chính">
    <a class="nav-item" href="/" data-x="1"><span aria-hidden="true">•</span> Quét</a>
    <a aria-current="page" class="nav-item" href="/rising/">Rising
       star<svg><title>biểu tượng</title></svg></a>
  </nav>
</aside>
<form method="post" action="/run/" data-autosubmit>
  <button class="x" disabled>Chạy ngay</button>
</form>
<form action="/loc/">
  <input name="q">
  <button>
    Lọc
  </button>
</form>
"""


def test_nav_links_reads_href_text_and_current() -> None:
    assert nav_links(PAGE) == [
        NavLink(href="/", text="Quét", current=False),
        NavLink(href="/rising/", text="Rising star", current=True),
    ]


def test_nav_links_of_a_missing_nav_is_empty() -> None:
    assert nav_links(PAGE, label="Không có") == []


def test_buttons_reads_text_and_disabled() -> None:
    assert buttons(PAGE) == [Button("Chạy ngay", disabled=True), Button("Lọc", disabled=False)]


def test_forms_groups_buttons_and_attrs() -> None:
    first, second = forms(PAGE)

    assert (first.method, first.action) == ("post", "/run/")
    assert "data-autosubmit" in first.attrs
    assert first.attrs["data-autosubmit"] is None
    assert first.buttons == (Button("Chạy ngay", disabled=True),)
    assert (second.method, second.action) == ("get", "/loc/")
    assert "data-autosubmit" not in second.attrs
    assert second.buttons == (Button("Lọc", disabled=False),)
