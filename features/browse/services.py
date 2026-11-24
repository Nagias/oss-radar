"""Nghiệp vụ trang Khám phá (F-010, F-012): ba tab Trending / Đang lên / Toàn kho.

Chỉ đọc CSDL, không gọi API. Đọc dữ liệu của tính năng khác qua `services.py` của chúng: nhãn
(`taxonomy`), điểm (`scoring`), rising star, trending và số tăng (`rising`), lần quét (`discovery`).

- **Toàn kho:** lọc và sắp trong CSDL (~40.000 repo); chỉ 50 dòng đang hiện được chấm điểm ngay.
  Repo "Nghi cao" bị ẩn theo điểm lưu sẵn (QĐ-19).
- **Trending / Đang lên:** lọc repo trong CSDL, lấy dòng đã xác minh của báo cáo mới nhất
  (`rising.latest_report_rows`, vài trăm dòng mỗi ngày do ngân sách xác minh), chấm điểm có số tăng,
  ẩn "Nghi cao" theo điểm tính trực tiếp (như báo cáo rising), rồi sắp và chia trang trong Python.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from django.db.models import Count, F, Max, Q, QuerySet
from django.http import QueryDict
from django.urls import reverse
from django.utils import formats, timezone

from features.browse import filters as f
from features.browse.filters import SORT_STARS as SORT_STARS
from features.browse.filters import TAB_ALL as TAB_ALL
from features.browse.filters import TAB_RISING as TAB_RISING
from features.browse.filters import TAB_TRENDING as TAB_TRENDING
from features.browse.filters import TABS as TABS
from features.browse.filters import BrowseFilters as BrowseFilters
from features.browse.forms import BrowseForm
from features.browse.models import SavedView
from features.catalog.models import Repository
from features.discovery import services as discovery
from features.rising import services as rising
from features.rising.models import DailyRun
from features.scoring import services as scoring
from features.taxonomy import services as taxonomy
from features.taxonomy.services import UNCLASSIFIED as UNCLASSIFIED

PAGE_SIZE = 50  # tab Toàn kho
REPORT_PAGE_SIZE = 25  # tab Trending / Đang lên: mỗi dòng nặng hơn (số tăng, biểu đồ, lý do)
LANGUAGES_SHOWN = 30
# Giấy phép cho phép dùng thương mại, sửa và bán mà không phải công khai mã của mình (MPL-2.0 chỉ
# buộc công khai file đã sửa của chính thư viện). GPL / AGPL / không giấy phép thì không có ở đây.
COMMERCIAL_LICENSES = (
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "0BSD",
    "Unlicense",
    "Zlib",
    "MPL-2.0",
    "CC0-1.0",
)
# Cách sắp của tab Toàn kho (giữ tên cũ cho trang và test của F-010).
SORTS = {key: f.SORT_LABELS[key] for key in f.TAB_SORTS[TAB_ALL]}


@dataclass(frozen=True, slots=True)
class BrowseRow:
    repository: Repository
    labels: taxonomy.RepoLabels | None
    scores: scoring.RepoScores
    gain_7d: int | None


@dataclass(frozen=True, slots=True)
class BrowsePage:
    rows: list[BrowseRow]
    total: int
    page: int
    pages: int
    counts: dict[str, int] = field(default_factory=dict)
    languages: list[str] = field(default_factory=list)

    @property
    def first_index(self) -> int:
        """Số thứ tự của dòng đầu trang (để đánh số 51, 52… ở trang 2)."""
        return (self.page - 1) * PAGE_SIZE + 1


@dataclass(frozen=True, slots=True)
class ExplorePage:
    """Một trang Khám phá. Tab Toàn kho dùng `all_rows`; Trending / Đang lên dùng `report_rows`."""

    tab: str
    sort: str
    all_rows: list[BrowseRow]
    report_rows: list[rising.RisingRow]
    total: int
    page: int
    pages: int
    page_size: int
    # Báo cáo mới nhất (cả ba tab hiện ngày của nó); None = chưa có báo cáo nào.
    run: DailyRun | None
    window_start: date | None = None
    hidden_count: int = 0  # repo "Nghi cao" bị ẩn (tab Trending / Đang lên)
    unverified_count: int = 0  # ứng viên cùng nhóm chưa xác minh được ở báo cáo đó
    counts: dict[str, int] = field(default_factory=dict)
    languages: list[str] = field(default_factory=list)

    @property
    def first_index(self) -> int:
        return (self.page - 1) * self.page_size + 1

    @property
    def trending_skipped(self) -> bool:
        """Báo cáo mới nhất không xác minh trending (không token, hoặc lượt trước F-011)."""
        return self.tab == TAB_TRENDING and self.run is not None and self.run.trending_budget == 0


@dataclass(frozen=True, slots=True)
class TabLink:
    key: str
    label: str
    url: str
    current: bool


@dataclass(frozen=True, slots=True)
class Chip:
    """Một ô lọc đang bật; bấm ✕ (`remove_url`) để gỡ riêng ô đó."""

    label: str
    remove_url: str


def explore(filters: BrowseFilters) -> ExplorePage:
    if filters.tab == TAB_ALL:
        whole = browse(filters)
        latest = rising.latest_report_run()
        return ExplorePage(
            tab=TAB_ALL,
            sort=filters.effective_sort,
            all_rows=whole.rows,
            report_rows=[],
            total=whole.total,
            page=whole.page,
            pages=whole.pages,
            page_size=PAGE_SIZE,
            run=latest,
            counts=whole.counts,
            languages=whole.languages,
        )
    kind = rising.KIND_TRENDING if filters.tab == TAB_TRENDING else rising.KIND_RISING
    latest_rows = rising.latest_report_rows(kind, _filtered(filters, Repository.objects.all()))
    rows = latest_rows.rows
    hidden = 0
    if not filters.show_suspicious:
        kept = [row for row in rows if not row.scores.suspicion.is_hidden]
        hidden, rows = len(rows) - len(kept), kept
    rows = _sorted_rows(rows, filters.effective_sort)
    pages = max(1, math.ceil(len(rows) / REPORT_PAGE_SIZE))
    page = min(max(1, filters.page), pages)
    return ExplorePage(
        tab=filters.tab,
        sort=filters.effective_sort,
        all_rows=[],
        report_rows=rows[(page - 1) * REPORT_PAGE_SIZE : page * REPORT_PAGE_SIZE],
        total=len(rows),
        page=page,
        pages=pages,
        page_size=REPORT_PAGE_SIZE,
        run=latest_rows.run,
        window_start=latest_rows.window_start,
        hidden_count=hidden,
        unverified_count=latest_rows.unverified_count,
        counts=taxonomy.label_counts(),
        languages=_languages(),
    )


def browse(filters: BrowseFilters) -> BrowsePage:
    """Tab Toàn kho: lọc, sắp, chia trang trong CSDL."""
    sort = filters.sort if filters.sort in f.TAB_SORTS[TAB_ALL] else SORT_STARS
    repos = _ordered(_annotated_filtered(filters), sort)
    total = repos.count()
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(1, filters.page), pages)
    shown = list(repos[(page - 1) * PAGE_SIZE : page * PAGE_SIZE])
    labels = taxonomy.labels_for(repo.pk for repo in shown)
    scores = scoring.score_repositories(shown)
    rows = [
        BrowseRow(
            repository=repo,
            labels=labels.get(repo.pk),
            scores=scores[repo.pk],
            gain_7d=getattr(repo, "latest_gain", None),
        )
        for repo in shown
    ]
    return BrowsePage(
        rows=rows,
        total=total,
        page=page,
        pages=pages,
        counts=taxonomy.label_counts(),
        languages=_languages(),
    )


def tab_links(filters: BrowseFilters) -> list[TabLink]:
    """Link ba tab: giữ bộ lọc chung (và góc nhìn đang mở), bỏ cách sắp và về trang 1."""
    return [
        TabLink(
            key=key,
            label=label,
            url=_link(replace(filters, tab=key, sort="", page=1)),
            current=key == filters.tab,
        )
        for key, label in TABS.items()
    ]


def active_chips(filters: BrowseFilters) -> list[Chip]:
    """Các ô lọc đang bật, mỗi ô một chip có link gỡ riêng ô đó (gỡ không cần JavaScript)."""
    names = {
        category.code: category.name
        for category in (*taxonomy.load_taxonomy().audience, *taxonomy.load_taxonomy().aspects)
    }
    chips: list[Chip] = []

    def add(label: str, field_name: str, value: str | None = None) -> None:
        chips.append(Chip(label, _link(f.without(filters, field_name, value))))

    if filters.q:
        add(f"Từ khoá: {filters.q}", "q")
    for code in filters.audience:
        add(f"Dành cho ai: {names.get(code, code)}", "audience", code)
    for code in filters.aspects:
        add(f"Làm được gì: {names.get(code, code)}", "aspects", code)
    if filters.language:
        add(f"Ngôn ngữ: {filters.language}", "language")
    if filters.min_stars is not None:
        add(f"Từ {_number(filters.min_stars)} star", "min_stars")
    if filters.max_stars is not None:
        add(f"Tới {_number(filters.max_stars)} star", "max_stars")
    if filters.created_days is not None:
        add(f"Tạo trong {_number(filters.created_days)} ngày", "created_days")
    if filters.commercial:
        add("Giấy phép dùng thương mại", "commercial")
    if filters.unclassified:
        add("Chưa phân loại", "unclassified")
    if filters.show_suspicious:
        add("Hiện cả repo nghi star giả", "show_suspicious")
    if filters.scan is not None:
        add(f"Lần quét #{filters.scan}", "scan")
    return chips


def has_more_filters(filters: BrowseFilters) -> bool:
    """Có ô nào trong phần "Lọc thêm" đang bật không (để mở sẵn phần đó)."""
    return any(
        (
            filters.audience,
            filters.aspects,
            filters.language,
            filters.min_stars is not None,
            filters.max_stars is not None,
            filters.created_days is not None,
            filters.commercial,
            filters.unclassified,
            filters.show_suspicious,
        )
    )


def clear_url(filters: BrowseFilters) -> str:
    """ "Xoá tất cả": giữ tab đang xem (và góc nhìn đang mở), bỏ mọi ô lọc."""
    return _link(BrowseFilters(tab=filters.tab, view=filters.view))


def page_url(filters: BrowseFilters, page: int) -> str:
    return _link(replace(filters, page=page))


def show_suspicious_url(filters: BrowseFilters) -> str:
    return _link(replace(filters, show_suspicious=True, page=1))


def _link(filters: BrowseFilters) -> str:
    return f.link(reverse("browse:explore"), filters)


def _number(value: int) -> str:
    return formats.number_format(value, force_grouping=True)


def _sorted_rows(rows: list[rising.RisingRow], sort: str) -> list[rising.RisingRow]:
    """Sắp ổn định: hoà thì giữ thứ tự tăng nhiều trước mà `latest_report_rows` đã có."""
    keys: dict[str, Callable[[rising.RisingRow], float]] = {
        "gain": lambda row: -row.check.gain_7d,
        "percent": lambda row: -(row.growth_percent or 0.0),
        SORT_STARS: lambda row: -row.check.stars,
        "quality": lambda row: -row.scores.quality.total,
        "potential": lambda row: -(row.scores.potential.total if row.scores.potential else 0),
        "created": lambda row: -row.repository.gh_created_at.timestamp(),
    }
    return sorted(rows, key=keys[sort])


def _filtered(filters: BrowseFilters, repos: QuerySet[Repository]) -> QuerySet[Repository]:
    """Ô lọc chung của ba tab (không gồm ẩn "Nghi cao": mỗi tab ẩn theo cách riêng)."""
    if filters.audience:
        repos = repos.filter(
            pk__in=taxonomy.repository_ids_with_labels("audience", filters.audience)
        )
    if filters.aspects:
        repos = repos.filter(pk__in=taxonomy.repository_ids_with_labels("aspects", filters.aspects))
    if filters.unclassified:
        repos = repos.exclude(pk__in=taxonomy.classified_repository_ids())
    for word in filters.search_words:
        repos = repos.filter(
            Q(full_name__icontains=word)
            | Q(description__icontains=word)
            | Q(topics__icontains=word)
        )
    if filters.language:
        repos = repos.filter(language__iexact=filters.language)
    if filters.min_stars is not None:
        repos = repos.filter(stars__gte=filters.min_stars)
    if filters.max_stars is not None:
        repos = repos.filter(stars__lte=filters.max_stars)
    if filters.created_days is not None:
        repos = repos.filter(
            gh_created_at__gte=timezone.now() - timedelta(days=filters.created_days)
        )
    if filters.commercial:
        repos = repos.filter(license_spdx__in=COMMERCIAL_LICENSES)
    if filters.scan is not None:
        repos = repos.filter(pk__in=discovery.repositories_seen_in([filters.scan]).values("pk"))
    return repos


def _annotated_filtered(filters: BrowseFilters) -> QuerySet[Repository]:
    repos: QuerySet[Repository] = scoring.with_cached_scores(Repository.objects.all()).annotate(
        latest_gain=rising.latest_gain_subquery()
    )
    repos = _filtered(filters, repos)
    if not filters.show_suspicious:
        repos = scoring.hide_high_suspicion(repos)
    return repos


def _ordered(repos: QuerySet[Repository], sort: str) -> QuerySet[Repository]:
    if sort == "forks":
        return repos.order_by("-forks", "full_name")
    if sort == "gain":
        return repos.order_by(F("latest_gain").desc(nulls_last=True), "-stars", "full_name")
    if sort == "quality":
        return repos.order_by(F("cached_quality").desc(nulls_last=True), "-stars", "full_name")
    if sort == "created":
        return repos.order_by("-gh_created_at", "full_name")
    if sort == "pushed":
        return repos.order_by(F("gh_pushed_at").desc(nulls_last=True), "full_name")
    return repos.order_by("-stars", "full_name")


def _languages() -> list[str]:
    """Ngôn ngữ có trong kho, nhiều repo trước — cho ô chọn ngôn ngữ."""
    rows = (
        Repository.objects.exclude(language="")
        .values("language")
        .annotate(n=Count("pk"))
        .order_by("-n", "language")[:LANGUAGES_SHOWN]
    )
    return [str(row["language"]) for row in rows]


# --- Góc nhìn đã lưu (F-012) ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ViewLink:
    """Một góc nhìn ở thanh bên / trang quản lý: link mở nó, có đang mở không, tóm tắt bộ lọc."""

    view: SavedView
    url: str
    current: bool
    summary: str


@dataclass(frozen=True, slots=True)
class SaveState:
    """Ô "Lưu góc nhìn" trên trang Khám phá.

    - `opened`: góc nhìn đang mở (tham số `view`); `changed`: bộ lọc đã khác góc đó → "Cập nhật".
    - `matching`: không mở góc nào nhưng bộ lọc trùng một góc đã lưu → chỉ báo tên, không lưu trùng.
    - Không có cả hai → form "Lưu góc nhìn" với `query` là chuỗi chuẩn của bộ lọc hiện tại.
    """

    query: str
    opened: SavedView | None = None
    changed: bool = False
    matching: SavedView | None = None


def filters_from_query(query: str) -> BrowseFilters:
    """Đọc lại chuỗi bộ lọc (đã lưu hoặc trên địa chỉ) qua chính form của trang."""
    return BrowseForm(QueryDict(query)).filters()


def view_url(view: SavedView) -> str:
    """Link mở góc nhìn: bộ lọc của nó kèm `view=<id>` để trang nhận ra góc đang mở."""
    return _link(replace(filters_from_query(view.query), view=view.pk))


def summary(filters: BrowseFilters) -> str:
    """Tóm tắt một dòng: tab, các ô lọc đang bật, cách sắp nếu khác mặc định."""
    parts = [TABS[filters.tab], *(chip.label for chip in active_chips(filters))]
    if filters.effective_sort != f.TAB_SORTS[filters.tab][0]:
        parts.append(f"sắp theo {f.SORT_LABELS[filters.effective_sort].lower()}")
    return " · ".join(parts)


def saved_views(current: BrowseFilters | None = None) -> list[ViewLink]:
    """Mọi góc nhìn theo thứ tự; `current` (bộ lọc trang Khám phá đang mở) để đánh dấu góc đang xem.

    Đang mở một góc (`view=<id>`) thì đánh dấu góc đó dù bộ lọc đã đổi; không thì đánh dấu góc
    có bộ lọc trùng. Trang khác (`current=None`) không đánh dấu góc nào.
    """
    canonical = None if current is None else f.canonical_query(current)
    links = []
    for view in SavedView.objects.all():
        filters = filters_from_query(view.query)
        if current is None:
            is_current = False
        elif current.view is not None:
            is_current = current.view == view.pk
        else:
            is_current = canonical == view.query
        links.append(
            ViewLink(
                view=view,
                url=_link(replace(filters, view=view.pk)),
                current=is_current,
                summary=summary(filters),
            )
        )
    return links


def save_state(filters: BrowseFilters) -> SaveState:
    query = f.canonical_query(filters)
    views = list(SavedView.objects.all())
    opened = next((view for view in views if view.pk == filters.view), None)
    if opened is not None:
        return SaveState(query=query, opened=opened, changed=opened.query != query)
    matching = next((view for view in views if view.query == query), None)
    return SaveState(query=query, matching=matching)


def save_view(name: str, query: str) -> SavedView:
    """Lưu góc nhìn mới ở cuối danh sách (`name`, `query` đã qua `SavedViewForm`)."""
    last = SavedView.objects.aggregate(last=Max("position"))["last"]
    return SavedView.objects.create(name=name, query=query, position=(last or 0) + 1)


def update_view(view: SavedView, *, name: str, query: str) -> SavedView:
    view.name, view.query = name, query
    view.save(update_fields=["name", "query", "updated_at"])
    return view


def delete_view(view: SavedView) -> None:
    view.delete()
