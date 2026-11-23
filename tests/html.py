"""Đọc trang HTML theo ý nghĩa cho test: link điều hướng, nút, form.

Test so ý nghĩa (nhãn, đích link, nút có bị khoá không) thay vì so nguyên chuỗi HTML, nên đổi
giao diện (thêm lớp, đổi thứ tự thuộc tính, chèn biểu tượng) không làm vỡ test mà vẫn kiểm đủ.
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser

MAIN_NAV_LABEL = "Các trang chính"
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "wbr",
}

Attrs = dict[str, str | None]


@dataclass(frozen=True)
class NavLink:
    href: str
    text: str
    current: bool


@dataclass(frozen=True)
class Button:
    text: str
    disabled: bool


@dataclass(frozen=True)
class Form:
    method: str
    action: str
    attrs: Attrs
    buttons: tuple[Button, ...]


@dataclass
class _Open:
    tag: str
    hidden: bool


@dataclass
class _Capture:
    attrs: Attrs
    parts: list[str] = field(default_factory=list)

    def text(self) -> str:
        return " ".join("".join(self.parts).split())


class _PageReader(HTMLParser):
    def __init__(self, nav_label: str) -> None:
        super().__init__(convert_charrefs=True)
        self.nav_label = nav_label
        self.stack: list[_Open] = []
        self.hidden_depth = 0
        self.nav_depth: int | None = None
        self.link: _Capture | None = None
        self.button: _Capture | None = None
        self.form: tuple[Attrs, list[Button]] | None = None
        self.nav_links: list[NavLink] = []
        self.buttons: list[Button] = []
        self.forms: list[Form] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found: Attrs = dict(attrs)
        if tag == "nav" and self.nav_depth is None and found.get("aria-label") == self.nav_label:
            self.nav_depth = len(self.stack)
        elif tag == "a" and self.nav_depth is not None:
            self.link = _Capture(found)
        elif tag == "button":
            self.button = _Capture(found)
        elif tag == "form":
            self.form = (found, [])
        if tag in _VOID_TAGS:
            return
        hidden = tag == "svg" or found.get("aria-hidden") == "true"
        self.stack.append(_Open(tag, hidden))
        self.hidden_depth += hidden

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS or not any(item.tag == tag for item in self.stack):
            return
        while self.stack:
            item = self.stack.pop()
            self.hidden_depth -= item.hidden
            if item.tag == tag:
                break
        if tag == "a" and self.link is not None:
            self.nav_links.append(
                NavLink(
                    href=self.link.attrs.get("href") or "",
                    text=self.link.text(),
                    current=self.link.attrs.get("aria-current") == "page",
                )
            )
            self.link = None
        elif tag == "nav" and self.nav_depth is not None and len(self.stack) == self.nav_depth:
            self.nav_depth = None
        elif tag == "button" and self.button is not None:
            button = Button(self.button.text(), disabled="disabled" in self.button.attrs)
            self.buttons.append(button)
            if self.form is not None:
                self.form[1].append(button)
            self.button = None
        elif tag == "form" and self.form is not None:
            attrs, form_buttons = self.form
            self.forms.append(
                Form(
                    method=(attrs.get("method") or "get").lower(),
                    action=attrs.get("action") or "",
                    attrs=attrs,
                    buttons=tuple(form_buttons),
                )
            )
            self.form = None

    def handle_data(self, data: str) -> None:
        if self.hidden_depth:
            return
        for capture in (self.link, self.button):
            if capture is not None:
                capture.parts.append(data)


def _read(page: str, nav_label: str = MAIN_NAV_LABEL) -> _PageReader:
    reader = _PageReader(nav_label)
    reader.feed(page)
    reader.close()
    return reader


def nav_links(page: str, label: str = MAIN_NAV_LABEL) -> list[NavLink]:
    """Các link trong `<nav aria-label=label>` đầu tiên của trang, theo thứ tự."""
    return _read(page, label).nav_links


def buttons(page: str) -> list[Button]:
    """Mọi nút `<button>` theo thứ tự; chữ gộp khoảng trắng, bỏ phần ẩn với trình đọc màn hình."""
    return _read(page).buttons


def forms(page: str) -> list[Form]:
    """Mọi form của trang kèm các nút bên trong; `method` mặc định "get" như trình duyệt."""
    return _read(page).forms
