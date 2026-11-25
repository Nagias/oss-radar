"""Đọc báo cáo của một lượt cho trang web: bảng rising star, mục chưa xác minh, phân trang."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import OuterRef, QuerySet, Subquery
from django.utils import formats, timezone

from features.catalog.models import Repository
from features.rising import growth
from features.rising._common import _growth_facts
from features.rising.models import DailyRun, DailyRunScan, RisingCheck
from features.scoring import services as scoring
from features.scoring.services import Score
from features.taxonomy import services as taxonomy

# --- Đọc báo cáo -----------------------------------------------------------------------------


# Thứ tự bảng rising star: theo điểm Tiềm năng (mặc định, F-006) hoặc theo số tăng 7 ngày.
SORT_POTENTIAL = "potential"
SORT_GAIN = "gain"

# Số dòng mỗi trang của báo cáo. Một dòng rising nặng ~3,4 KB (kèm giải thích từng điểm), một dòng
# chưa xác minh ~1,2 KB: giữ trang mặc định dưới ~150 KB dù lượt có hàng trăm dòng — trang tự tải
# lại mỗi 10 giây khi lượt hôm nay đang chạy.
RISING_PAGE_SIZE = 25
UNVERIFIED_PAGE_SIZE = 20


@dataclass(frozen=True, slots=True)
class PageInfo:
    """Vị trí của trang đang xem trong một danh sách dài (tổng dòng, trang mấy trên mấy)."""

    total: int
    page: int
    pages: int
    size: int

    @property
    def first_index(self) -> int:
        """Số thứ tự của dòng đầu trang (để đánh số 26, 27… ở trang 2)."""
        return (self.page - 1) * self.size + 1


def _paginate[T](rows: list[T], page: int, size: int) -> tuple[list[T], PageInfo]:
    """Cắt lấy trang `page`; số trang ngoài khoảng thì về trang đầu/cuối gần nhất."""
    pages = max(1, math.ceil(len(rows) / size))
    page = min(max(1, page), pages)
    shown = rows[(page - 1) * size : page * size]
    return shown, PageInfo(total=len(rows), page=page, pages=pages, size=size)


@dataclass(frozen=True, slots=True)
class RisingRow:
    """Một dòng của bảng rising star, kèm sẵn mọi thứ trang cần hiện (không tính trong template)."""

    check: RisingCheck
    repository: Repository
    is_new_entry: bool
    growth_percent: float | None
    age_days: int
    flag_labels: tuple[str, ...]
    sparkline: str
    reason: str
    scores: scoring.RepoScores
    labels: taxonomy.RepoLabels | None  # None = chưa phân loại


@dataclass(frozen=True, slots=True)
class UnverifiedRow:
    """Ứng viên chưa xác minh: số tăng chỉ là ước lượng, điểm Tiềm năng cũng ghi "(ước lượng)"."""

    check: RisingCheck
    potential: Score


@dataclass(frozen=True, slots=True)
class DailyReport:
    run: DailyRun
    # Chỉ các dòng của trang đang xem; tổng số dòng và số trang nằm ở `rising_page`.
    rising: list[RisingRow]
    rising_page: PageInfo
    # Dòng qua bộ lọc nhưng "Nghi cao" star giả: ẩn khỏi bảng chính, có nút hiện (kèm lý do).
    hidden: list[RisingRow]
    unverified: list[UnverifiedRow]  # trang đang xem; tổng ở `unverified_page`
    unverified_page: PageInfo
    scans: list[DailyRunScan]
    # Số dòng đã xác minh bằng lịch sử chính thức, bất kể ngưỡng lọc của người xem.
    verified_count: int
    # Số rising star của lượt (ngưỡng mặc định, như `run.rising_count`) bị ẩn vì "Nghi cao".
    hidden_rising_count: int


def daily_report(
    run: DailyRun,
    *,
    max_stars: int = growth.RISING_MAX_STARS,
    min_gain: int = growth.RISING_MIN_GAIN_7D,
    sort: str = SORT_POTENTIAL,
    audience: Sequence[str] = (),
    aspects: Sequence[str] = (),
    page: int = 1,
    unverified_page: int = 1,
) -> DailyReport:
    """Báo cáo của một lượt, lọc theo ngưỡng người dùng chọn. Chỉ đọc dữ liệu đã lưu, không gọi API.

    - Bảng rising: dòng đã xác minh bằng lịch sử chính thức, dưới `max_stars` star và tăng từ
      `min_gain` trong 7 ngày; sắp theo điểm Tiềm năng (hoà thì tăng nhiều trước), hoặc theo số
      tăng 7 ngày khi `sort="gain"`.
    - Dòng "Nghi cao" star giả (sau bộ lọc) nằm ở `hidden`, không ở bảng chính.
    - "Mới vào danh sách": repo không là rising star trong báo cáo liền trước.
    - Mục chưa xác minh: dòng còn là ước lượng (hết ngân sách xác minh, hoặc GitHub trả lỗi).
    - Điểm tính lúc xem (không lưu), từ số liệu repo và hồ sơ chủ đang có trong kho.
    - `audience` / `aspects` (F-010): chỉ giữ repo có ít nhất một nhãn đã chọn ở mỗi lớp được chọn
      (HOẶC trong một lớp, VÀ giữa hai lớp) — như trang Kho repo.
    - Bảng rising và mục chưa xác minh chia trang riêng (`page`, `unverified_page`): mỗi trang
      `RISING_PAGE_SIZE` / `UNVERIFIED_PAGE_SIZE` dòng. Dòng bị ẩn không chia trang (thường ít).
    """
    # Chỉ nhóm rising: dòng trending (repo từ 1.000 star, F-011) có trang riêng.
    checks = RisingCheck.objects.filter(daily_run=run, pool=RisingCheck.Pool.RISING).select_related(
        "repository"
    )
    all_verified = list(checks.filter(source=RisingCheck.Source.HISTORY).order_by("-gain_7d", "pk"))
    unverified = list(checks.exclude(source=RisingCheck.Source.HISTORY).order_by("-gain_7d", "pk"))
    every = [*all_verified, *unverified]
    scores = scoring.score_repositories(
        [check.repository for check in every],
        growth={check.repository_id: _growth_facts(check) for check in every},
    )
    labels = taxonomy.labels_for(check.repository_id for check in all_verified)
    verified = [
        check
        for check in all_verified
        if check.stars < max_stars
        and check.gain_7d >= min_gain
        and _has_labels(labels.get(check.repository_id), audience=audience, aspects=aspects)
    ]
    # "Mới vào danh sách": hôm trước chưa nằm trong danh sách với CÙNG ngưỡng đang lọc.
    previous = _reported_runs().filter(day__lt=run.day).order_by("-day").first()
    previous_rising: set[int] = set()
    if previous is not None:
        previous_rising = set(
            previous.checks.filter(
                pool=RisingCheck.Pool.RISING,
                source=RisingCheck.Source.HISTORY,
                stars__lt=max_stars,
                gain_7d__gte=min_gain,
            ).values_list("repository_id", flat=True)
        )
    rows = [
        _rising_row(
            check,
            run=run,
            is_new_entry=check.repository_id not in previous_rising,
            reason=_reason(check, max_stars=max_stars, min_gain=min_gain),
            scores=scores[check.repository_id],
            labels=labels.get(check.repository_id),
        )
        for check in verified
    ]
    if sort != SORT_GAIN:
        # Sắp ổn định: hoà điểm thì giữ thứ tự tăng nhiều trước đã có.
        rows.sort(key=lambda row: -_potential_total(row.scores))
    hidden_rising = sum(
        1
        for check in all_verified
        if check.is_rising and scores[check.repository_id].suspicion.is_hidden
    )
    rising, rising_page = _paginate(
        [row for row in rows if not row.scores.suspicion.is_hidden], page, RISING_PAGE_SIZE
    )
    shown_unverified, unverified_info = _paginate(unverified, unverified_page, UNVERIFIED_PAGE_SIZE)
    return DailyReport(
        run=run,
        rising=rising,
        rising_page=rising_page,
        hidden=[row for row in rows if row.scores.suspicion.is_hidden],
        unverified=[
            UnverifiedRow(check, _estimated_potential(scores[check.repository_id]))
            for check in shown_unverified
        ],
        unverified_page=unverified_info,
        scans=list(run.scans.select_related("scan_run", "watch_query").order_by("position", "pk")),
        verified_count=len(all_verified),
        hidden_rising_count=hidden_rising,
    )


# Hai loại danh sách của trang Khám phá (F-012).
KIND_TRENDING = "trending"
KIND_RISING = "rising"


@dataclass(frozen=True, slots=True)
class LatestRows:
    """Dòng trending hoặc rising của báo cáo mới nhất (đã xác minh), tăng nhiều trước.

    `unverified_count`: số ứng viên cùng nhóm còn là ước lượng (hết ngân sách / GitHub lỗi), không
    tính bộ lọc — để trang Khám phá nói rõ còn bao nhiêu repo chưa xét được.
    """

    run: DailyRun | None
    rows: list[RisingRow]
    unverified_count: int
    # Ngày UTC đầu của cửa sổ 7 ngày đã tính số tăng (ngày cuối là `run.window_end`).
    window_start: date | None = None


def latest_report_rows(kind: str, repositories: QuerySet[Repository] | None = None) -> LatestRows:
    """Dòng `kind` ("trending" / "rising") của báo cáo mới nhất, chỉ repo thuộc `repositories`.

    Trending lấy mọi dòng `is_trending` (cả repo nhỏ tăng ≥ 200 star); rising lấy dòng `is_rising`.
    Điểm tính kèm số tăng (như `daily_report`) để mức nghi star giả có cả tín hiệu "dồn một ngày".
    "Mới": cùng loại mà không có trong báo cáo liền trước. Số câu truy vấn không phụ thuộc số dòng.
    """
    run = latest_report_run()
    if run is None:
        return LatestRows(run=None, rows=[], unverified_count=0)
    trending = kind == KIND_TRENDING
    marker = {"is_trending": True} if trending else {"is_rising": True}
    checks = RisingCheck.objects.filter(daily_run=run, source=RisingCheck.Source.HISTORY, **marker)
    if repositories is not None:
        checks = checks.filter(repository__in=repositories.values("pk"))
    chosen = list(checks.select_related("repository").order_by("-gain_7d", "pk"))
    pool = RisingCheck.Pool.TRENDING if trending else RisingCheck.Pool.RISING
    unverified_count = (
        RisingCheck.objects.filter(daily_run=run, pool=pool)
        .exclude(source=RisingCheck.Source.HISTORY)
        .count()
    )
    previous = _reported_runs().filter(day__lt=run.day).order_by("-day").first()
    seen_before: set[int] = set()
    if previous is not None:
        seen_before = set(
            previous.checks.filter(source=RisingCheck.Source.HISTORY, **marker).values_list(
                "repository_id", flat=True
            )
        )
    scores = scoring.score_repositories(
        [check.repository for check in chosen],
        growth={check.repository_id: _growth_facts(check) for check in chosen},
    )
    labels = taxonomy.labels_for(check.repository_id for check in chosen)
    rows = [
        _rising_row(
            check,
            run=run,
            is_new_entry=check.repository_id not in seen_before,
            reason=_trending_reason(check) if trending else None,
            scores=scores[check.repository_id],
            labels=labels.get(check.repository_id),
        )
        for check in chosen
    ]
    window_start = (
        None if run.window_end is None else run.window_end - timedelta(days=growth.WINDOW_DAYS - 1)
    )
    return LatestRows(
        run=run, rows=rows, unverified_count=unverified_count, window_start=window_start
    )


def latest_gain_subquery() -> Subquery:
    """Biểu thức cho `annotate`: star tăng 7 ngày (lịch sử chính thức) ở lần xét gần nhất của repo.

    Repo chưa từng được xác minh thì trống.
    """
    return Subquery(
        RisingCheck.objects.filter(repository=OuterRef("pk"), source=RisingCheck.Source.HISTORY)
        .order_by("-daily_run__day", "-pk")
        .values("gain_7d")[:1]
    )


def latest_report_run() -> DailyRun | None:
    """Lượt mới nhất đã lập xong báo cáo (trang Rising star mở báo cáo này mặc định)."""
    return _reported_runs().order_by("-day").first()


def reported_run(run_id: int) -> DailyRun | None:
    """Lượt `run_id` nếu đã lập xong báo cáo; chưa xong (đang chạy, lỗi, dừng) thì None."""
    return _reported_runs().filter(pk=run_id).first()


def report_run_for(day: date) -> DailyRun | None:
    """Lượt đã lập xong báo cáo của ngày `day` (giờ Việt Nam); chưa có thì None."""
    return _reported_runs().filter(day=day).first()


def report_days() -> list[date]:
    """Các ngày có báo cáo, mới trước — để chọn xem báo cáo ngày khác."""
    return list(_reported_runs().order_by("-day").values_list("day", flat=True))


def _reported_runs() -> QuerySet[DailyRun]:
    """Lượt đã xong ở bước lập báo cáo. Lượt bị đóng khi hết ngày ở bước trước thì không tính."""
    return DailyRun.objects.filter(
        step=DailyRun.Step.REPORT,
        status__in=[DailyRun.Status.SUCCEEDED, DailyRun.Status.SUCCEEDED_PARTIAL],
    )


def _has_labels(
    labels: taxonomy.RepoLabels | None, *, audience: Sequence[str], aspects: Sequence[str]
) -> bool:
    if not audience and not aspects:
        return True
    if labels is None:
        return False
    audience_ok = not audience or any(c.code in audience for c in labels.audience)
    aspects_ok = not aspects or any(c.code in aspects for c in labels.aspects)
    return audience_ok and aspects_ok


def _potential_total(scores: scoring.RepoScores) -> int:
    return scores.potential.total if scores.potential is not None else 0


def _estimated_potential(scores: scoring.RepoScores) -> Score:
    if scores.potential is None:
        raise ValueError("Dòng chưa xác minh phải có điểm Tiềm năng (đã truyền số tăng ước lượng)")
    return scores.potential


def _rising_row(
    check: RisingCheck,
    *,
    run: DailyRun,
    is_new_entry: bool,
    reason: str | None,
    scores: scoring.RepoScores,
    labels: taxonomy.RepoLabels | None,
) -> RisingRow:
    """`reason=None`: dòng "Vì sao có mặt" theo ngưỡng rising mặc định."""
    repository = check.repository
    # Tuổi tính tới ngày của lượt (không phải hôm nay): xem lại báo cáo cũ vẫn khớp cờ
    # "Repo rất mới".
    age_days = (run.day - timezone.localdate(repository.gh_created_at)).days
    return RisingRow(
        check=check,
        repository=repository,
        is_new_entry=is_new_entry,
        growth_percent=growth.growth_percent_7d(check.stars, check.gain_7d),
        age_days=age_days,
        flag_labels=tuple(growth.FLAG_LABELS[growth.Flag(flag)] for flag in check.flags),
        sparkline=growth.sparkline_points(check.series),
        reason=reason
        if reason is not None
        else _reason(check, max_stars=growth.RISING_MAX_STARS, min_gain=growth.RISING_MIN_GAIN_7D),
        scores=scores,
        labels=labels,
    )


def _reason(check: RisingCheck, *, max_stars: int, min_gain: int) -> str:
    """Dòng "Vì sao có mặt" (thiết kế mục 4): con số, ngưỡng, nguồn và khoảng ngày UTC đã dùng."""
    return (
        f"+{_number(check.gain_7d)} star trong 7 ngày (ngưỡng {_number(min_gain)}) · "
        f"đang {_number(check.stars)} star (dưới {_number(max_stars)}) · {_source(check)}"
    )


def _trending_reason(check: RisingCheck) -> str:
    """Dòng "Vì sao có mặt" của trending: ngưỡng là số star VÀ phần trăm (QĐ-22), mọi cỡ repo."""
    min_gain = _number(growth.TRENDING_MIN_GAIN_7D)
    return (
        f"+{_number(check.gain_7d)} star trong 7 ngày (ngưỡng {min_gain} star và "
        f"{growth.TRENDING_MIN_PERCENT_7D:g}%) · đang {_number(check.stars)} star · "
        f"{_source(check)}"
    )


def _source(check: RisingCheck) -> str:
    window_end = check.window_end
    if window_end is None:
        raise ValueError(f"Dòng xét #{check.pk} đã xác minh mà thiếu ngày UTC cuối của cửa sổ")
    window_start = window_end - timedelta(days=growth.WINDOW_DAYS - 1)
    # Gạch nối khoảng ngày giữ đúng mẫu ở mục 4 của thiết kế.
    return f"nguồn: lịch sử star GitHub, ngày UTC {window_start:%d/%m}–{window_end:%d/%m}"  # noqa: RUF001


def _number(value: int) -> str:
    """Số kiểu Việt Nam, có dấu ngăn nghìn "." (1.000) — cùng cách bộ lọc `intcomma` ở trang web."""
    return formats.number_format(value, force_grouping=True)
