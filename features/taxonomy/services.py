"""Nghiệp vụ phân loại repo bằng AI (F-010). Tính năng khác chỉ gọi các hàm ở đây.

AI chỉ gắn nhãn trong bộ nhóm (`categories.toml`), không đánh giá, không tạo số liệu. Mỗi lô gọi
AI được lưu ngay khi có kết quả: hỏng giữa chừng (hết ngân sách, 9router tắt, bấm Dừng) không mất
phần đã xong, và lần sau không gọi lại repo đã có nhãn mà mô tả không đổi.
"""

import logging
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Count, F, Q, QuerySet, Sum
from django.utils import timezone

from features.catalog.models import Repository
from features.taxonomy.categories import Category
from features.taxonomy.categories import load_taxonomy as load_taxonomy
from features.taxonomy.models import ClassifyMiss, ClassifyRun, RepoClassification, RepoLabel
from features.taxonomy.prompt import (
    PROMPT_VERSION,
    LabelParseError,
    Labels,
    RepoForPrompt,
    build_messages,
    fingerprint,
    parse_labels,
)
from integrations.github.pacing import CallBudget, CallBudgetExhaustedError, Sleep
from integrations.llm.client import LlmClient, get_llm_client
from integrations.llm.errors import LlmError, LlmResponseError

logger = logging.getLogger(__name__)

# Xuất lại cho tính năng khác (chỉ được import `taxonomy.services`).
Origin = ClassifyRun.Origin

BATCH_SIZE = 40  # repo mỗi lượt gọi AI: ~2.000 token nền mỗi lượt (đo 2026-10-27) nên gom nhiều
# Lần phân loại không ghi nhịp sống quá chừng này thì coi như app đã tắt giữa chừng. Lúc chờ 9router
# hồi lượt vẫn ghi nhịp sống (`heartbeat_sleep`); một lượt HTTP dài nhất `LLM_TIMEOUT_SECONDS`.
LIVE_WINDOW = timedelta(minutes=10)
HEARTBEAT_CHUNK_SECONDS = 10.0
# Repo AI không phân loại được từ chừng này lần thì nghỉ một thời gian (temperature=0: hỏng là hỏng
# lại) — không đốt lượt mỗi nhịp 5 phút cho đúng mấy repo đó.
MAX_MISSES = 2
MISS_REST = timedelta(days=7)
UNCLASSIFIED = "__unclassified__"  # khoá đếm số repo chưa có nhãn trong `label_counts`
REASON_INTERRUPTED = "Bị gián đoạn (app tắt giữa chừng)."
REASON_UNEXPECTED = "Lỗi không mong đợi — xem log của máy chủ."
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
    """Repo chưa có nhãn, hoặc mô tả / topics / ngôn ngữ đã đổi từ lần kiểm trước.

    `reclassify`: thêm repo được gắn nhãn bằng prompt hay bộ nhóm cũ, và cả repo đang nghỉ vì AI
    không phân loại được. Thứ tự: nhiều star trước.

    Mô tả chỉ đổi được khi repo được quét lại (`upsert_repositories` ghi `last_seen_at`), nên chỉ
    xét repo chưa có nhãn hoặc được thấy lại sau lần kiểm trước; repo xét rồi mà mô tả không đổi
    được ghi `checked_at` để lần sau khỏi xét — việc nền gọi hàm này mỗi 5 phút.
    """
    now = timezone.now()
    repos = (among if among is not None else Repository.objects.all()).select_related(
        "classification"
    )
    if not reclassify:
        repos = repos.filter(
            Q(classification__isnull=True)
            | Q(classification__checked_at__isnull=True)
            | Q(last_seen_at__gt=F("classification__checked_at"))
        ).exclude(
            classify_miss__misses__gte=MAX_MISSES, classify_miss__last_missed_at__gt=now - MISS_REST
        )
    current = (PROMPT_VERSION, load_taxonomy().version)
    needed: list[Repository] = []
    unchanged: list[int] = []
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
        elif previous is not None:
            unchanged.append(previous.pk)
    for start in range(0, len(unchanged), _IN_BATCH):
        RepoClassification.objects.filter(pk__in=unchanged[start : start + _IN_BATCH]).update(
            checked_at=now
        )
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

    - `before_each()` chạy trước mỗi lượt gọi (bên gọi ghi nhịp sống, ném lỗi khi bấm Dừng).
    - `after_batch(số repo đã xét)` chạy sau mỗi lô xong (để in tiến độ).
    - Lô bị từ chối (bộ lọc an toàn, 4xx, trả rỗng) hoặc trả lời hỏng → **chia đôi** và gọi lại
      từng nửa, tới khi khoanh được repo gây lỗi; repo đó ghi vào `ClassifyMiss` rồi đi tiếp. Không
      thì một lô xấu làm kẹt mãi cả việc phân loại (repo luôn xếp theo star).
    - Repo AI bỏ sót cũng ghi vào `ClassifyMiss`; hỏng `MAX_MISSES` lần thì nghỉ `MISS_REST`.
    - Lỗi khoá, hết lượt, 9router tắt, hết ngân sách → ném ra; các lô trước đã lưu.
    """
    taxonomy = load_taxonomy()
    outcome = ClassifyOutcome()
    queue = deque(
        list(repos[start : start + BATCH_SIZE]) for start in range(0, len(repos), BATCH_SIZE)
    )
    done = 0
    while queue:
        batch = queue.popleft()
        before_each()
        calls_before = llm.calls_made
        failure = ""
        labels: dict[int, Labels] = {}
        model = llm.model
        try:
            result = llm.complete(build_messages(taxonomy, [_for_prompt(r) for r in batch]))
        except LlmResponseError as exc:  # lỗi của riêng lô này, không phải của 9router
            failure = str(exc)
        else:
            model = result.model or model
            ClassifyRun.objects.filter(pk=run.pk).update(
                prompt_tokens=F("prompt_tokens") + result.prompt_tokens,
                completion_tokens=F("completion_tokens") + result.completion_tokens,
            )
            try:
                labels = parse_labels(
                    result.content,
                    taxonomy=taxonomy,
                    expected_ids={repo.github_id for repo in batch},
                )
            except LabelParseError as exc:
                failure = str(exc)
        finally:
            _count_calls(run, llm.calls_made - calls_before, outcome)
        if failure:
            logger.warning("Phân loại #%s: lô %s repo hỏng: %s", run.pk, len(batch), failure)
            ClassifyRun.objects.filter(pk=run.pk).update(error=failure[:500])
            if len(batch) > 1:
                half = len(batch) // 2
                queue.appendleft(batch[half:])
                queue.appendleft(batch[:half])
                continue
        _save(run, batch, labels, model=model, taxonomy_version=taxonomy.version)
        missed = [repo for repo in batch if repo.github_id not in labels]
        _record_misses(missed, reason=failure or "AI bỏ sót repo này trong câu trả lời")
        outcome.classified += len(labels)
        outcome.missing += len(missed)
        outcome.missed_ids.extend(repo.pk for repo in missed)
        done += len(batch)
        after_batch(done)
    run.refresh_from_db()
    return outcome


def heartbeat_sleep(run: ClassifyRun, *, also: Callable[[], None] | None = None) -> Sleep:
    """Hàm ngủ cho client AI: ngủ từng khúc ≤ 10 giây, sau mỗi khúc ghi nhịp sống của lần phân loại.

    Chờ 9router hồi lượt có khi vài phút: không ghi nhịp sống thì lần khác (lệnh `classify`) tưởng
    lần này đã chết rồi chạy chồng. `also()` để bên gọi ghi nhịp sống của chính nó (lượt hằng ngày)
    và ném lỗi khi người dùng bấm Dừng.
    """

    def sleep(seconds: float) -> None:
        remaining = seconds
        while remaining > 0:
            step = min(HEARTBEAT_CHUNK_SECONDS, remaining)
            time.sleep(step)
            remaining -= step
            ClassifyRun.objects.filter(pk=run.pk).update(heartbeat_at=timezone.now())
            if also is not None:
                also()

    return sleep


@dataclass(frozen=True, slots=True)
class CatalogReport:
    run: ClassifyRun | None  # None = không có gì cần phân loại
    needed: int
    retried: int
    stopped: str  # lý do dừng sớm (hết ngân sách); rỗng = chạy hết


def classify_catalog(
    *,
    budget: int,
    limit: int | None = None,
    reclassify: bool = False,
    on_progress: Callable[[int, int], None] = lambda _done, _total: None,
    on_retry: Callable[[int], None] = lambda _count: None,
) -> CatalogReport:
    """Phân loại bù cả kho (lệnh `classify`): tối đa `budget` lượt gọi, thử lại một lần repo bỏ sót.

    Đo thật: ~2% lô Gemini trả lời hỏng một cách ngẫu nhiên → thử lại ngay thay vì đợi ngày sau.
    Ném `ClassifyBusyError` khi đang có lần phân loại khác, `LlmError` khi 9router hỏng hẳn (lần
    phân loại được đóng kèm lý do trước khi ném). Ctrl+C cũng đóng lần phân loại rồi ném lại.
    """
    repos = repositories_needing_labels(reclassify=reclassify)
    if limit is not None:
        repos = repos[:limit]
    if not repos:
        return CatalogReport(run=None, needed=0, retried=0, stopped="")
    run = start_classify_run(Origin.COMMAND)
    stopped = ""
    retried = 0
    error = ""
    try:
        with get_llm_client(sleep=heartbeat_sleep(run), budget=CallBudget(budget)) as llm:
            outcome = classify(
                run, repos, llm=llm, after_batch=lambda d: on_progress(d, len(repos))
            )
            missed = set(outcome.missed_ids)
            if missed:
                retry = [repo for repo in repos if repo.pk in missed]
                retried = len(retry)
                on_retry(retried)
                classify(run, retry, llm=llm, after_batch=lambda d: on_progress(d, len(retry)))
    except CallBudgetExhaustedError:
        stopped = f"Hết ngân sách {budget} lượt gọi."
    except LlmError as exc:
        error = str(exc)
        raise
    except KeyboardInterrupt:
        error = "Dừng tay (Ctrl+C)."
        raise
    except BaseException:
        error = REASON_UNEXPECTED
        raise
    finally:
        finish_classify_run(run, error=error)
    return CatalogReport(run=run, needed=len(repos), retried=retried, stopped=stopped)


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
                    "checked_at": now,
                },
            )
            ClassifyMiss.objects.filter(repository=repo).delete()
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


def _record_misses(repos: list[Repository], *, reason: str) -> None:
    """Repo AI chưa phân loại được: cộng một lần hỏng (đủ `MAX_MISSES` lần thì nghỉ `MISS_REST`)."""
    now = timezone.now()
    for repo in repos:
        miss, created = ClassifyMiss.objects.get_or_create(
            repository=repo, defaults={"misses": 1, "last_missed_at": now, "reason": reason[:300]}
        )
        if not created:
            ClassifyMiss.objects.filter(pk=miss.pk).update(
                misses=F("misses") + 1, last_missed_at=now, reason=reason[:300]
            )


def _categories(
    lookup: Callable[[str], Category | None], pairs: list[tuple[str, str]], axis: str
) -> tuple[Category, ...]:
    found = (lookup(code) for pair_axis, code in pairs if pair_axis == axis)
    return tuple(category for category in found if category is not None)
