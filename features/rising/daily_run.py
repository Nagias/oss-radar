"""Vòng đời lượt hằng ngày: bắt đầu, dừng, tự chạy tiếp, lịch 7:00, phân loại dần kho bằng AI."""

import logging
import uuid
from datetime import date, datetime

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core import background
from features.discovery import services as discovery
from features.discovery.models import ScanRun
from features.rising._common import (
    _SCAN_UNFINISHED,
    _UNEXPECTED_REASON,
    BACKLOG_CALLS_PER_TICK,
    BACKLOG_PAUSE_AFTER_ERROR,
    DAILY_RUN_AFTER,
    MAX_AUTO_CONTINUES,
    REASON_BUSY_APP,
    REASON_CTRL_C,
    REASON_INTERRUPTED,
    REASON_STOPPED,
    RETRY_LATER_AFTER,
    DailyRunBlockedError,
    DailySupersededError,
    _summary,
)
from features.rising._runner import _DailyRunner
from features.rising.models import DailyRun
from features.taxonomy import services as taxonomy
from integrations.github.pacing import (
    CallBudget,
    CallBudgetExhaustedError,
)
from integrations.llm.client import get_llm_client, llm_configured
from integrations.llm.errors import LlmError

logger = logging.getLogger(__name__)


# --- Nhịp sống, dọn lượt cũ ------------------------------------------------------------------


def live_daily_run() -> DailyRun | None:
    """Lượt đang chạy thật: nhịp sống của chính lượt, hoặc của lần quét con, còn mới.

    Ở bước quét lại, lượt không tự ghi nhịp sống trong lúc lần quét con chạy (có khi hàng chục
    phút) — lần quét con còn sống thì lượt còn sống. Nhịp sống luôn so với giờ thật, vì nó được ghi
    bằng giờ thật.
    """
    threshold = timezone.now() - discovery.LIVE_HEARTBEAT_WINDOW
    for run in DailyRun.objects.filter(status=DailyRun.Status.RUNNING):
        if _is_live(run, threshold):
            return run
    return None


def pause_stale_daily_runs() -> int:
    """Lượt "đang chạy" mà nhịp sống (của lượt lẫn lần quét con) đã cũ → bị gián đoạn → Tạm dừng.

    Người dùng đã bấm Dừng (ở trang lượt, hoặc ở trang lần quét con) nhưng app tắt trước khi luồng
    chạy kịp thấy → ghi là "bấm Dừng", không phải "bị gián đoạn", để không tự chạy tiếp ngược ý họ.
    """
    threshold = timezone.now() - discovery.LIVE_HEARTBEAT_WINDOW
    paused = 0
    for run in DailyRun.objects.filter(status=DailyRun.Status.RUNNING):
        if _is_live(run, threshold):
            continue
        if run.stop_requested or _child_stop_requested(run):
            kind, reason = DailyRun.PauseKind.STOPPED, REASON_STOPPED
        else:
            kind, reason = DailyRun.PauseKind.INTERRUPTED, REASON_INTERRUPTED
        paused += DailyRun.objects.filter(
            pk=run.pk, status=DailyRun.Status.RUNNING, heartbeat_at=run.heartbeat_at
        ).update(
            status=DailyRun.Status.PAUSED,
            pause_kind=kind,
            stop_reason=reason,
            paused_at=timezone.now(),
            runner_token="",
        )
    return paused


def close_previous_days(today: date) -> int:
    """Lượt của ngày trước `today` chưa xong (bị gián đoạn, đang Tạm dừng) → "Xong nhưng còn sót".

    Không cố chạy nốt lượt cũ: báo cáo tính theo ngày. Lượt cũ còn đang chạy thật thì để nó tự xong.
    Lần quét dở của lượt cũ vẫn Tạm dừng, tiếp tục bằng tay được ở trang lần quét đó.
    """
    threshold = timezone.now() - discovery.LIVE_HEARTBEAT_WINDOW
    closed = 0
    unfinished = DailyRun.objects.filter(
        day__lt=today, status__in=[DailyRun.Status.RUNNING, DailyRun.Status.PAUSED]
    )
    for run in unfinished:
        if _is_live(run, threshold):
            continue
        problems = [*run.problems, f"Hết ngày — lượt dừng ở bước «{run.get_step_display()}»."]
        closed += DailyRun.objects.filter(
            pk=run.pk, status=run.status, heartbeat_at=run.heartbeat_at
        ).update(
            status=DailyRun.Status.SUCCEEDED_PARTIAL,
            problems=problems,
            stop_reason=_summary(problems),
            pause_kind="",
            runner_token="",
            finished_at=timezone.now(),
        )
    return closed


# --- Bắt đầu, dừng, lịch ---------------------------------------------------------------------


def prepare_daily_run(*, now: datetime | None = None) -> DailyRun:
    """Bấm "Chạy ngay" / lệnh `daily`: tạo lượt hôm nay, hoặc mở lại lượt đang Tạm dừng / Lỗi.

    Lượt trả về đã giữ chỗ "đang chạy"; chạy thật bằng `execute_daily_run`. Từ chối
    (`DailyRunBlockedError`) khi đang có lần quét hay lượt khác chạy thật, hoặc hôm nay đã xong.
    Bấm trước 7:00 vẫn được: chỉ lịch tự động mới chờ 7:00.
    `now` là lúc bấm (quyết định ngày nào); nhịp sống luôn ghi bằng giờ thật.
    """
    moment = now if now is not None else timezone.now()
    today = timezone.localdate(moment)
    with transaction.atomic():
        close_previous_days(today)
        pause_stale_daily_runs()
        _ensure_nothing_live()
        run = DailyRun.objects.filter(day=today).first()
        if run is None:
            return DailyRun.objects.create(
                day=today,
                status=DailyRun.Status.RUNNING,
                step=DailyRun.Step.RESCAN,
                started_at=moment,
                heartbeat_at=timezone.now(),
            )
        if run.status in (DailyRun.Status.SUCCEEDED, DailyRun.Status.SUCCEEDED_PARTIAL):
            raise DailyRunBlockedError(
                f"Hôm nay đã quét xong ({run.get_status_display()}) — mỗi ngày chỉ một lượt, "
                "xem báo cáo ở trang Rising star."
            )
        reopened: dict[str, object] = {
            "status": DailyRun.Status.RUNNING,
            "runner_token": "",  # nhả mã: luồng cũ (nếu còn sống) thấy mất quyền và tự rút lui
            "stop_requested": False,
            "stop_reason": "",
            "pause_kind": "",
            "paused_at": None,
            "finished_at": None,
            "heartbeat_at": timezone.now(),
        }
        if run.status == DailyRun.Status.FAILED:
            reopened["error_message"] = ""
        DailyRun.objects.filter(pk=run.pk).update(**reopened)
        run.refresh_from_db()
    return run


def request_daily_stop(run: DailyRun) -> None:
    """Bấm Dừng ở trang lượt: luồng chạy dừng trước truy vấn kế tiếp.

    Đang quét lại thì dừng luôn lần quét con đang chạy. Lượt đang Tạm dừng chờ tự chạy tiếp thì
    thôi không tự chạy tiếp nữa. Lượt đã xong hoặc đã Lỗi thì không có gì để dừng.
    """
    DailyRun.objects.filter(
        pk=run.pk, status__in=[DailyRun.Status.RUNNING, DailyRun.Status.PAUSED]
    ).update(stop_requested=True)
    DailyRun.objects.filter(pk=run.pk, status=DailyRun.Status.PAUSED).update(
        pause_kind=DailyRun.PauseKind.STOPPED, stop_reason=REASON_STOPPED
    )
    run.refresh_from_db()
    if run.status != DailyRun.Status.RUNNING or run.step != DailyRun.Step.RESCAN:
        return
    children = run.scans.select_related("scan_run").filter(scan_run__status=ScanRun.Status.RUNNING)
    for link in children:
        if link.scan_run.is_live:
            discovery.request_stop(link.scan_run)


def release_unstarted_daily_run(run: DailyRun) -> None:
    """Lượt vừa giữ chỗ nhưng luồng nền đã bị việc khác chiếm → Tạm dừng, chờ bấm Chạy tiếp.

    Không để nó "đang chạy" nằm chờ sau một việc dài: nhịp sống sẽ cũ đi và nó bị coi là gián đoạn.
    Ghi là "bấm Dừng" (không phải gián đoạn) nên cũng không bị tự chạy tiếp.
    """
    DailyRun.objects.filter(pk=run.pk, status=DailyRun.Status.RUNNING, runner_token="").update(
        status=DailyRun.Status.PAUSED,
        pause_kind=DailyRun.PauseKind.STOPPED,
        stop_reason=REASON_BUSY_APP,
        paused_at=timezone.now(),
        heartbeat_at=None,
        runner_token="",
    )
    run.refresh_from_db()


def run_daily_if_due(*, now: datetime | None = None) -> DailyRun | None:
    """Việc định kỳ (trên luồng nền): đến lượt thì chạy lượt hôm nay tại chỗ, tới khi dừng.

    - Lượt ngày trước còn dở thì đóng lại; lượt "đang chạy" mà nhịp sống đã cũ thì coi là gián đoạn.
    - Đang có lần quét hay lượt chạy thật (kể cả ở cửa sổ khác) → chờ nhịp sau.
    - Lượt hôm nay bị gián đoạn, hoặc bị GitHub/mạng chặn từ 15 phút trở lên → tự chạy tiếp (tối đa
      3 lần).
    - Hôm nay chưa có lượt và đã quá 7:00 → bắt đầu (mở app muộn thì chạy bù ngay nhịp đầu).

    `now` chỉ dùng cho quyết định theo lịch; nhịp sống luôn so với giờ thật vì nó được ghi bằng giờ
    thật. Trả lượt vừa chạy, hoặc `None` nếu chưa đến lượt.
    """
    moment = now if now is not None else timezone.now()
    today = timezone.localdate(moment)
    close_previous_days(today)
    pause_stale_daily_runs()
    if discovery.live_scan() is not None or live_daily_run() is not None:
        return None
    run = DailyRun.objects.filter(day=today).first()
    if run is None:
        if timezone.localtime(moment).time() < DAILY_RUN_AFTER:
            return None
        try:
            run = prepare_daily_run(now=moment)
        except DailyRunBlockedError as exc:
            # Tiến trình khác vừa bắt đầu quét sau lần kiểm ở trên: chờ nhịp sau.
            logger.info("Chưa bắt đầu lượt hằng ngày: %s", exc)
            return None
    elif not _reopen_for_auto_continue(run, moment):
        return None
    logger.info("Chạy lượt quét hằng ngày %s", run.day)
    background.relabel(f"Lượt quét hằng ngày {run.day:%d/%m}")
    execute_daily_run(run.pk)
    run.refresh_from_db()
    return run


# --- Chạy lượt -------------------------------------------------------------------------------


def execute_daily_run(run_id: int) -> None:
    """Chạy lượt từ bước đang dở tới khi xong, tạm dừng hoặc lỗi. Gọi từ luồng nền hoặc lệnh."""
    token = uuid.uuid4().hex
    claimed = DailyRun.objects.filter(
        pk=run_id, status=DailyRun.Status.RUNNING, runner_token=""
    ).update(runner_token=token, heartbeat_at=timezone.now())
    if not claimed:
        logger.info(
            "Bỏ qua lượt hằng ngày #%s: không ở trạng thái chạy hoặc đã có luồng khác giữ", run_id
        )
        return
    runner = _DailyRunner(run_id, token=token)
    try:
        runner.run()
    except DailySupersededError:
        logger.info("Lượt hằng ngày #%s: luồng cũ rút lui, không ghi gì thêm", run_id)
    except KeyboardInterrupt:
        runner.pause(DailyRun.PauseKind.STOPPED, REASON_CTRL_C)
        raise
    except Exception as exc:
        logger.exception("Lượt hằng ngày #%s gặp lỗi không mong đợi", run_id)
        runner.fail(f"{_UNEXPECTED_REASON} (Chi tiết: {exc!r})")
        raise


def _is_live(run: DailyRun, threshold: datetime) -> bool:
    if run.status != DailyRun.Status.RUNNING:
        return False
    if run.heartbeat_at is not None and run.heartbeat_at >= threshold:
        return True
    # Từ bước lọc thô trở đi, lượt tự ghi nhịp sống: lần quét con đang chạy lúc đó (vd lần quét bị
    # bỏ lại được bấm Tiếp tục bằng tay) không được giữ một lượt đã chết là "còn sống".
    if run.step != DailyRun.Step.RESCAN:
        return False
    # Xét nhịp sống của lần quét con bất kể trạng thái: lần quét con vừa xong (nhịp sống còn mới)
    # mà lượt chưa kịp ghi nhịp sống của mình thì lượt vẫn đang chạy, không phải bị gián đoạn.
    return run.scans.filter(scan_run__heartbeat_at__gte=threshold).exists()


def _child_stop_requested(run: DailyRun) -> bool:
    """Lần quét con làm gần nhất đã bị bấm Dừng, mà app tắt trước khi lượt kịp ghi "Tạm dừng".

    Hai cách bị lỡ: lần quét con chưa kịp thấy cờ Dừng (cờ còn nguyên), hoặc đã dừng xong theo cờ
    nhưng lượt chưa kịp xử lý kết quả đó. Chỉ xét lần quét làm gần nhất, và chỉ khi lượt còn ở bước
    quét lại: lần quét dở cũ (của truy vấn đã tắt) không được biến lần gián đoạn sau thành
    "bấm Dừng".
    """
    if run.step != DailyRun.Step.RESCAN:
        return False
    latest = (
        run.scans.select_related("scan_run")
        .order_by(F("scan_run__heartbeat_at").desc(nulls_last=True), "-position", "-pk")
        .first()
    )
    if latest is None:
        return False
    scan = latest.scan_run
    if scan.status in _SCAN_UNFINISHED and scan.stop_requested:
        return True
    return scan.status == ScanRun.Status.PAUSED and scan.stop_reason == discovery.REASON_STOPPED


def _ensure_nothing_live() -> None:
    live_run = live_daily_run()
    if live_run is not None:
        raise DailyRunBlockedError(f"Lượt quét hằng ngày {live_run.day:%d/%m} đang chạy.")
    scan = discovery.live_scan()
    if scan is not None:
        raise DailyRunBlockedError(
            f"Đang có lần quét #{scan.pk} chạy — chờ nó xong (hoặc bấm Dừng ở trang lần quét đó) "
            "rồi chạy lại."
        )


def _reopen_for_auto_continue(run: DailyRun, moment: datetime) -> bool:
    """Lượt hôm nay bị gián đoạn / bị chặn đủ lâu và còn lượt tự chạy tiếp → mở lại để chạy tiếp."""
    if run.status != DailyRun.Status.PAUSED or run.stop_requested:
        return False
    if run.auto_continue_count >= MAX_AUTO_CONTINUES:
        return False
    if run.pause_kind == DailyRun.PauseKind.RETRY_LATER:
        if run.paused_at is not None and run.paused_at > moment - RETRY_LATER_AFTER:
            return False
    elif run.pause_kind != DailyRun.PauseKind.INTERRUPTED:
        return False
    # Đếm cùng lúc với mở lại, TRƯỚC khi chạy: lượt làm sập app vẫn bị đếm, không lặp mãi.
    reopened = DailyRun.objects.filter(
        pk=run.pk,
        status=DailyRun.Status.PAUSED,
        stop_requested=False,
        auto_continue_count=run.auto_continue_count,
    ).update(
        status=DailyRun.Status.RUNNING,
        runner_token="",
        pause_kind="",
        stop_reason="",
        paused_at=None,
        heartbeat_at=timezone.now(),
        auto_continue_count=F("auto_continue_count") + 1,
        last_auto_continue_at=moment,
    )
    return reopened == 1


def classify_backlog_if_due(*, now: datetime | None = None) -> int:
    """Việc định kỳ: phân loại dần phần kho chưa có nhãn. Trả số lượt gọi AI đã dùng ở nhịp này.

    Chỉ chạy khi: đã có khoá AI, lượt hằng ngày hôm nay đã xong (không tranh luồng nền với lượt),
    chưa dùng hết `LLM_BACKLOG_CALLS_PER_DAY` lượt hôm nay, và lần trước không vừa lỗi (nghỉ 30
    phút — không gọi dồn khi 9router tắt hay khoá sai). Mỗi nhịp tối đa `BACKLOG_CALLS_PER_TICK`
    lượt để luồng nền không bị giữ lâu.
    """
    if not llm_configured():
        return 0
    moment = now if now is not None else timezone.now()
    today = timezone.localdate(moment)
    run = DailyRun.objects.filter(day=today).first()
    if run is None or run.status not in (
        DailyRun.Status.SUCCEEDED,
        DailyRun.Status.SUCCEEDED_PARTIAL,
    ):
        return 0
    left = settings.LLM_BACKLOG_CALLS_PER_DAY - taxonomy.ai_calls_on(
        today, origin=taxonomy.Origin.BACKLOG
    )
    if left <= 0:
        return 0
    failed_at = taxonomy.last_failure_at(taxonomy.Origin.BACKLOG)
    if failed_at is not None and failed_at > moment - BACKLOG_PAUSE_AFTER_ERROR:
        return 0
    repos = taxonomy.repositories_needing_labels()
    if not repos:
        return 0
    try:
        classify_run = taxonomy.start_classify_run(taxonomy.Origin.BACKLOG)
    except taxonomy.ClassifyBusyError:
        return 0
    background.relabel("Phân loại dần kho repo bằng AI")
    calls = min(BACKLOG_CALLS_PER_TICK, left)
    error = ""
    sleep = taxonomy.heartbeat_sleep(classify_run)
    try:
        with get_llm_client(sleep=sleep, budget=CallBudget(calls)) as llm:
            taxonomy.classify(classify_run, repos[: calls * taxonomy.BATCH_SIZE], llm=llm)
    except CallBudgetExhaustedError:
        logger.info("Phân loại dần: hết %s lượt của nhịp này", calls)
    except LlmError as exc:
        logger.warning("Phân loại dần kho bị ngắt, nghỉ 30 phút: %r", exc)
        error = str(exc)
    except BaseException:
        error = taxonomy.REASON_UNEXPECTED  # ghi "bị ngắt" để nghỉ 30 phút, rồi ném tiếp
        raise
    finally:
        taxonomy.finish_classify_run(classify_run, error=error)
    return classify_run.calls_used
