"""Nghiệp vụ trang Kho repo (F-010): duyệt toàn kho, lọc theo nhãn và số liệu, sắp, phân trang.

Chỉ đọc CSDL, không gọi API. Lọc và sắp chạy trong CSDL (32.000 repo); chỉ 50 dòng đang hiện mới
được chấm điểm trực tiếp để hiện phần giải thích. Đọc dữ liệu của tính năng khác qua
`services.py` của chúng: nhãn (`taxonomy`), điểm lưu sẵn (`scoring`), rising star và số tăng
(`rising`), lần quét (`discovery`).
"""

import math
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Count, F, Q, QuerySet
from django.utils import timezone

from features.catalog.models import Repository
from features.discovery import services as discovery
from features.rising import services as rising
from features.scoring import services as scoring
from features.taxonomy import services as taxonomy
from features.taxonomy.services import UNCLASSIFIED as UNCLASSIFIED

PAGE_SIZE = 50
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

SORT_STARS = "stars"
SORTS = {
    SORT_STARS: "Nhiều star",
    "forks": "Nhiều fork",
    "gain": "Tăng nhiều trong 7 ngày",
    "quality": "Điểm Chất lượng",
    "created": "Mới tạo",
    "pushed": "Mới đẩy code",
}


@dataclass(frozen=True, slots=True)
class BrowseFilters:
    """Bộ lọc của trang. Ô để trống = không lọc theo ô đó."""

    audience: tuple[str, ...] = ()
    aspects: tuple[str, ...] = ()
    q: str = ""
    language: str = ""
    min_stars: int | None = None
    max_stars: int | None = None
    created_days: int | None = None
    rising_only: bool = False
    show_suspicious: bool = False
    unclassified: bool = False
    commercial: bool = False
    scan: int | None = None
    sort: str = SORT_STARS
    page: int = 1


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


def browse(filters: BrowseFilters) -> BrowsePage:
    repos = _ordered(_filtered(filters), filters.sort)
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


def _filtered(filters: BrowseFilters) -> QuerySet[Repository]:
    repos: QuerySet[Repository] = scoring.with_cached_scores(Repository.objects.all()).annotate(
        latest_gain=rising.latest_gain_subquery()
    )
    if filters.audience:
        repos = repos.filter(
            pk__in=taxonomy.repository_ids_with_labels("audience", filters.audience)
        )
    if filters.aspects:
        repos = repos.filter(pk__in=taxonomy.repository_ids_with_labels("aspects", filters.aspects))
    if filters.unclassified:
        repos = repos.exclude(pk__in=taxonomy.classified_repository_ids())
    if filters.q:
        repos = repos.filter(
            Q(full_name__icontains=filters.q) | Q(description__icontains=filters.q)
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
    if filters.rising_only:
        repos = repos.filter(pk__in=rising.latest_rising_repository_ids())
    if filters.commercial:
        repos = repos.filter(license_spdx__in=COMMERCIAL_LICENSES)
    if filters.scan is not None:
        repos = repos.filter(pk__in=discovery.repositories_seen_in([filters.scan]).values("pk"))
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
