"""Bộ lọc của trang Khám phá (F-010, F-012): tab, cách sắp, các ô lọc, cách viết ra địa chỉ.

Tách riêng để `forms.py` và `services.py` cùng dùng mà không import vòng. Hàm ở đây là hàm thuần:
không đọc CSDL.
"""

from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlencode

TAB_TRENDING = "trending"
TAB_RISING = "rising"
TAB_ALL = "all"
DEFAULT_TAB = TAB_TRENDING
TABS = {TAB_TRENDING: "Trending", TAB_RISING: "Đang lên", TAB_ALL: "Toàn kho"}

SORT_STARS = "stars"
SORT_LABELS = {
    "gain": "Tăng 7 ngày",
    "percent": "% tăng 7 ngày",
    "potential": "Điểm Tiềm năng",
    SORT_STARS: "Nhiều star",
    "forks": "Nhiều fork",
    "quality": "Điểm Chất lượng",
    "created": "Mới tạo",
    "pushed": "Mới đẩy code",
}
# Cách sắp của từng tab; cái đầu là mặc định.
TAB_SORTS = {
    TAB_TRENDING: ("gain", "percent", SORT_STARS, "quality"),
    TAB_RISING: ("potential", "gain", "percent", "quality", "created"),
    TAB_ALL: (SORT_STARS, "forks", "gain", "quality", "created", "pushed"),
}
# Tìm nhiều từ (VÀ): giữ tối đa 5 từ đầu để câu truy vấn CSDL không phình theo chữ người gõ.
MAX_SEARCH_WORDS = 5


@dataclass(frozen=True, slots=True)
class BrowseFilters:
    """Bộ lọc của trang. Ô để trống = không lọc theo ô đó; `sort` trống = mặc định của tab.

    `view`: góc nhìn đang mở (F-012), chỉ để nhận ra góc nhìn, không lọc gì.
    """

    tab: str = DEFAULT_TAB
    audience: tuple[str, ...] = ()
    aspects: tuple[str, ...] = ()
    q: str = ""
    language: str = ""
    min_stars: int | None = None
    max_stars: int | None = None
    created_days: int | None = None
    show_suspicious: bool = False
    unclassified: bool = False
    commercial: bool = False
    scan: int | None = None
    sort: str = ""
    page: int = 1
    view: int | None = None

    @property
    def effective_sort(self) -> str:
        """Cách sắp thật sự dùng: giá trị lạ hoặc của tab khác thì về mặc định của tab."""
        sorts = TAB_SORTS[self.tab]
        return self.sort if self.sort in sorts else sorts[0]

    @property
    def search_words(self) -> list[str]:
        return self.q.split()[:MAX_SEARCH_WORDS]


def params(filters: BrowseFilters, *, saved_only: bool = False) -> list[tuple[str, str]]:
    """Các ô đang khác mặc định, theo thứ tự cố định (giá trị nhiều lựa chọn đã sắp).

    `saved_only`: chỉ phần định nghĩa một góc nhìn — bỏ `scan`, `view`, `page` (thiết kế F-012).
    """
    pairs: list[tuple[str, str]] = []
    if filters.tab != DEFAULT_TAB:
        pairs.append(("tab", filters.tab))
    # Góc nhìn: viết gọn để hai bộ lọc lọc ra cùng kết quả có cùng một chuỗi (từ khoá chỉ dùng 5
    # từ đầu, ngôn ngữ không phân biệt hoa thường, "từ 0 star" là không lọc).
    q = " ".join(filters.search_words) if saved_only else filters.q
    if q:
        pairs.append(("q", q))
    pairs += [("audience", code) for code in sorted(set(filters.audience))]
    pairs += [("aspects", code) for code in sorted(set(filters.aspects))]
    if filters.language:
        pairs.append(("language", filters.language.lower() if saved_only else filters.language))
    min_stars = None if saved_only and filters.min_stars == 0 else filters.min_stars
    for name, number in (
        ("min_stars", min_stars),
        ("max_stars", filters.max_stars),
        ("created_days", filters.created_days),
    ):
        if number is not None:
            pairs.append((name, str(number)))
    for name, flag in (
        ("commercial", filters.commercial),
        ("unclassified", filters.unclassified),
        ("show_suspicious", filters.show_suspicious),
    ):
        if flag:
            pairs.append((name, "on"))
    if filters.effective_sort != TAB_SORTS[filters.tab][0]:
        pairs.append(("sort", filters.effective_sort))
    if not saved_only:
        if filters.scan is not None:
            pairs.append(("scan", str(filters.scan)))
        if filters.view is not None:
            pairs.append(("view", str(filters.view)))
        if filters.page > 1:
            pairs.append(("page", str(filters.page)))
    return pairs


def link(base: str, filters: BrowseFilters) -> str:
    """Địa chỉ `base` (trang Khám phá) kèm bộ lọc này; bộ lọc mặc định thì không có `?`."""
    query = urlencode(params(filters))
    return f"{base}?{query}" if query else base


def canonical_query(filters: BrowseFilters) -> str:
    """Chuỗi định nghĩa một góc nhìn: ổn định để so hai bộ lọc có giống nhau không."""
    return urlencode(params(filters, saved_only=True))


def without(filters: BrowseFilters, field: str, value: str | None = None) -> BrowseFilters:
    """Bộ lọc đã gỡ một ô (hoặc một giá trị của ô nhiều lựa chọn), về trang 1."""
    current = getattr(filters, field)
    changes: dict[str, Any] = {"page": 1}
    if isinstance(current, tuple):
        changes[field] = tuple(code for code in current if code != value)
    else:
        changes[field] = getattr(BrowseFilters(), field)  # giá trị "không lọc" của ô đó
    return replace(filters, **changes)
