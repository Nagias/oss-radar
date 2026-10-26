"""Nghiệp vụ phân loại repo bằng AI (F-010). Tính năng khác chỉ gọi các hàm ở đây.

AI chỉ gắn nhãn trong bộ nhóm (`categories.toml`), không đánh giá, không tạo số liệu. Mỗi lô gọi
AI được lưu ngay khi có kết quả: hỏng giữa chừng (hết ngân sách, 9router tắt, bấm Dừng) không mất
phần đã xong, và lần sau không gọi lại repo đã có nhãn mà mô tả không đổi.
"""

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Count, F, Q, QuerySet, Sum
from django.utils import timezone

from features.catalog.models import Repository
from features.taxonomy.categories import Category
from features.taxonomy.categories import load_taxonomy as load_taxonomy
from features.taxonomy.models import ClassifyRun, RepoClassification, RepoLabel
from features.taxonomy.prompt import (
    PROMPT_VERSION,
    LabelParseError,
    Labels,
    RepoForPrompt,
    build_messages,
    fingerprint,
    parse_labels,
)
from integrations.llm.client import LlmClient

logger = logging.getLogger(__name__)

# Xuất lại cho tính năng khác (chỉ được import `taxonomy.services`).
Origin = ClassifyRun.Origin

BATCH_SIZE = 40  # repo mỗi lượt gọi AI: ~2.000 token nền mỗi lượt (đo 2026-10-27) nên gom nhiều
# Lần phân loại không ghi nhịp sống quá chừng này thì coi như app đã tắt giữa chừng. Dài hơn lúc
# client chờ 9router hồi lượt (tối đa 5 phút).
LIVE_WINDOW = timedelta(minutes=10)
UNCLASSIFIED = "__unclassified__"  # khoá đếm số repo chưa có nhãn trong `label_counts`
REASON_INTERRUPTED = "Bị gián đoạn (app tắt giữa chừng)."
_IN_BATCH = 500  # SQLite giới hạn số tham số mỗi câu lệnh


class ClassifyBusyError(Exception):
    """Đang có lần phân loại khác chạy thật: không chạy chồng (gọi trùng, tốn gấp đôi)."""

    def __init__(self, run: ClassifyRun) -> None:
        super().__init__(f"Đang phân loại ({run.get_origin_display()}, #{run.pk}).")
        self.run = run


@dataclass(frozen=True, slots=True)
class RepoLabels:
    """Nhãn của một repo để hiển thị: chỉ các nhóm còn trong bộ nhóm hiện hành."""

    audience: tuple[Category, ...]
    aspects: tuple[Category, ...]
    reason: str


@dataclass(slots=True)
class ClassifyOutcome:
    classified: int = 0
    missing: int = 0  # repo AI bỏ sót hoặc trả sai dạng: lần sau thử lại
    calls: int = 0
    missed_ids: list[int] = field(default_factory=list)  # `Repository.pk` của các repo bỏ sót


# --- Chọn repo cần phân loại ------------------------------------------------------------------


def repositories_needing_labels(
    *, among: QuerySet[Repository] | None = None, reclassify: bool = False
) -> list[Repository]:
    """Repo chưa có nhãn, hoặc mô tả / topics / ngôn ngữ đã đổi từ lần phân loại trước.

    `reclassify`: thêm repo được gắn nhãn bằng prompt hay bộ nhóm cũ. Thứ tự: nhiều star trước.

    Mô tả chỉ đổi được khi repo được quét lại (`upsert_repositories` ghi `last_seen_at`), nên chỉ
    xét repo chưa có nhãn hoặc được thấy lại sau lần phân loại — việc nền gọi hàm này mỗi 5 phút,
    không được tính lại dấu vân tay của cả kho mỗi lần.
    """
    repos = (among if among is not None else Repository.objects.all()).select_related(
        "classification"
    )
    if not reclassify:
        repos = repos.filter(
            Q(classification__isnull=True) | Q(last_seen_at__gt=F("classification__classified_at"))
        )
    current = (PROMPT_VERSION, load_taxonomy().version)
    needed: list[Repository] = []
    for repo in repos.order_by("-stars", "pk").iterator(chunk_size=2000):
        # Quan hệ ngược một-một: repo chưa phân loại thì truy cập ném lỗi kiểu AttributeError.
        previous: RepoClassification | None = getattr(repo, "classification", None)
        changed = previous is None or previous.fingerprint != _fingerprint(repo)
        outdated = (
            reclassify
            and previous is not None
            and ((previous.prompt_version, previous.taxonomy_version) != current)
        )
        if changed or outdated:
            needed.append(repo)
    return needed


# --- Lần phân loại ---------------------------------------------------------------------------


def start_classify_run(origin: str) -> ClassifyRun:
    """Mở một lần phân loại. Lần cũ mất nhịp sống thì đóng lại; lần khác còn sống thì từ chối."""
    now = timezone.now()
    with transaction.atomic():
        ClassifyRun.objects.filter(
            status=ClassifyRun.Status.RUNNING, heartbeat_at__lt=now - LIVE_WINDOW
        ).update(status=ClassifyRun.Status.FAILED, error=REASON_INTERRUPTED, finished_at=now)
        live = ClassifyRun.objects.filter(status=ClassifyRun.Status.RUNNING).first()
        if live is not None:
            raise ClassifyBusyError(live)
        return ClassifyRun.objects.create(origin=origin)


def finish_classify_run(run: ClassifyRun, *, error: str = "") -> None:
    fields: dict[str, object] = {
        "status": ClassifyRun.Status.FAILED if error else ClassifyRun.Status.DONE,
        "finished_at": timezone.now(),
    }
    if error:
        fields["error"] = error
    ClassifyRun.objects.filter(pk=run.pk).update(**fields)
    run.refresh_from_db()


def classify(
    run: ClassifyRun,
    repos: Sequence[Repository],
    *,
    llm: LlmClient,
    before_each: Callable[[], None] = lambda: None,
    after_batch: Callable[[int], None] = lambda _done: None,
) -> ClassifyOutcome:
    """Gắn nhãn cho `repos`, mỗi lô `BATCH_SIZE` repo một lượt gọi AI, lưu ngay sau mỗi lô.

    - `before_each()` chạy trước mỗi lô (bên gọi ghi nhịp sống, ném lỗi khi bấm Dừng).
    - `after_batch(số repo đã xét)` chạy sau mỗi lô (để in tiến độ).
    - Lô AI trả lời hỏng → ghi lý do vào `run.error`, đi tiếp lô sau.
    - Lỗi AI (khoá sai, hết lượt, 9router tắt) và hết ngân sách → ném ra; các lô trước đã lưu.
    """
    taxonomy = load_taxonomy()
    outcome = ClassifyOutcome()
    done = 0
    for start in range(0, len(repos), BATCH_SIZE):
        batch = list(repos[start : start + BATCH_SIZE])
        before_each()
        calls_before = llm.calls_made
        try:
            result = llm.complete(build_messages(taxonomy, [_for_prompt(r) for r in batch]))
        finally:
            _count_calls(run, llm.calls_made - calls_before, outcome)
        expected = {repo.github_id for repo in batch}
        try:
            labels = parse_labels(result.content, taxonomy=taxonomy, expected_ids=expected)
        except LabelParseError as exc:
            logger.warning("Phân loại #%s: một lô AI trả lời hỏng: %s", run.pk, exc)
            labels = {}
            ClassifyRun.objects.filter(pk=run.pk).update(error=str(exc)[:500])
        _save(
            run, batch, labels, model=result.model or llm.model, taxonomy_version=taxonomy.version
        )
        ClassifyRun.objects.filter(pk=run.pk).update(
            prompt_tokens=F("prompt_tokens") + result.prompt_tokens,
            completion_tokens=F("completion_tokens") + result.completion_tokens,
            heartbeat_at=timezone.now(),
        )
        outcome.classified += len(labels)
        outcome.missing += len(batch) - len(labels)
        outcome.missed_ids.extend(repo.pk for repo in batch if repo.github_id not in labels)
        done += len(batch)
        after_batch(done)
    run.refresh_from_db()
    return outcome


# --- Đọc nhãn cho trang ----------------------------------------------------------------------


def labels_for(repository_ids: Iterable[int]) -> dict[int, RepoLabels]:
    """Nhãn của các repo đã phân loại, theo `Repository.pk`. Repo chưa phân loại thì vắng mặt."""
    ids = sorted(set(repository_ids))
    taxonomy = load_taxonomy()
    reasons: dict[int, str] = {}
    codes: dict[int, list[tuple[str, str]]] = {}
    for start in range(0, len(ids), _IN_BATCH):
        chunk = ids[start : start + _IN_BATCH]
        reasons.update(
            RepoClassification.objects.filter(repository_id__in=chunk).values_list(
                "repository_id", "reason"
            )
        )
        for repository_id, axis, code in (
            RepoLabel.objects.filter(repository_id__in=chunk)
            .order_by("pk")
            .values_list("repository_id", "axis", "code")
        ):
            codes.setdefault(repository_id, []).append((axis, code))
    result: dict[int, RepoLabels] = {}
    for repository_id, reason in reasons.items():
        pairs = codes.get(repository_id, [])
        result[repository_id] = RepoLabels(
            audience=_categories(taxonomy.category, pairs, RepoLabel.Axis.AUDIENCE),
            aspects=_categories(taxonomy.category, pairs, RepoLabel.Axis.ASPECTS),
            reason=reason,
        )
    return result


def repository_ids_with_labels(axis: str, codes: Sequence[str]) -> QuerySet[RepoLabel, int]:
    """Truy vấn con: id repo có ÍT NHẤT MỘT nhãn trong `codes` ở lớp `axis` (HOẶC trong một lớp).

    Dùng làm `pk__in=` — không truyền danh sách id dài vào câu lệnh.
    """
    return RepoLabel.objects.filter(axis=axis, code__in=list(codes)).values_list(
        "repository_id", flat=True
    )


def classified_repository_ids() -> QuerySet[RepoClassification, int]:
    """Truy vấn con: id repo đã có nhãn (để lọc "Chưa phân loại")."""
    return RepoClassification.objects.values_list("repository_id", flat=True)


def label_counts() -> dict[str, int]:
    """Số repo theo từng mã nhóm (toàn kho), kèm số repo chưa phân loại ở khoá `UNCLASSIFIED`."""
    counts: dict[str, int] = dict(
        RepoLabel.objects.values_list("code").annotate(n=Count("repository_id", distinct=True))
    )
    counts[UNCLASSIFIED] = Repository.objects.count() - RepoClassification.objects.count()
    return counts


def last_failure_at(origin: str) -> datetime | None:
    """Lúc lần phân loại gần nhất của nguồn `origin` bị ngắt vì lỗi (để nghỉ, không gọi dồn)."""
    failed = (
        ClassifyRun.objects.filter(origin=origin, status=ClassifyRun.Status.FAILED)
        .exclude(finished_at=None)
        .order_by("-finished_at")
        .first()
    )
    return None if failed is None else failed.finished_at


def ai_calls_on(day: date, *, origin: str) -> int:
    """Tổng lượt gọi AI của các lần phân loại bắt đầu trong ngày `day` (giờ Việt Nam)."""
    total = ClassifyRun.objects.filter(started_at__date=day, origin=origin).aggregate(
        calls=Sum("calls_used")
    )["calls"]
    return int(total or 0)


# --- Hàm phụ ---------------------------------------------------------------------------------


def _fingerprint(repo: Repository) -> str:
    return fingerprint(repo.description, [str(topic) for topic in repo.topics], repo.language)


def _for_prompt(repo: Repository) -> RepoForPrompt:
    return RepoForPrompt(
        id=repo.github_id,
        full_name=repo.full_name,
        description=repo.description,
        topics=tuple(str(topic) for topic in repo.topics),
        language=repo.language,
    )


def _count_calls(run: ClassifyRun, calls: int, outcome: ClassifyOutcome) -> None:
    """Ghi lượt gọi ngay cả khi lỗi: lượt đã tiêu không được "biến mất" khỏi sổ."""
    if calls:
        outcome.calls += calls
        ClassifyRun.objects.filter(pk=run.pk).update(
            calls_used=F("calls_used") + calls, heartbeat_at=timezone.now()
        )


def _save(
    run: ClassifyRun,
    batch: list[Repository],
    labels: dict[int, Labels],
    *,
    model: str,
    taxonomy_version: int,
) -> None:
    now = timezone.now()
    with transaction.atomic():
        for repo in batch:
            found = labels.get(repo.github_id)
            if found is None:
                continue
            RepoClassification.objects.update_or_create(
                repository=repo,
                defaults={
                    "reason": found.reason,
                    "model": model[:100],
                    "prompt_version": PROMPT_VERSION,
                    "taxonomy_version": taxonomy_version,
                    "fingerprint": _fingerprint(repo),
                    "classified_at": now,
                },
            )
            RepoLabel.objects.filter(repository=repo).delete()
            RepoLabel.objects.bulk_create(
                [
                    RepoLabel(repository=repo, axis=RepoLabel.Axis.AUDIENCE, code=c)
                    for c in found.audience
                ]
                + [
                    RepoLabel(repository=repo, axis=RepoLabel.Axis.ASPECTS, code=c)
                    for c in found.aspects
                ]
            )
        ClassifyRun.objects.filter(pk=run.pk).update(
            classified_count=F("classified_count") + len(labels)
        )


def _categories(
    lookup: Callable[[str], Category | None], pairs: list[tuple[str, str]], axis: str
) -> tuple[Category, ...]:
    found = (lookup(code) for pair_axis, code in pairs if pair_axis == axis)
    return tuple(category for category in found if category is not None)
