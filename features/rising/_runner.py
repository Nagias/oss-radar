"""Luồng chạy một lượt hằng ngày (`_DailyRunner`): các bước từ quét lại tới lập báo cáo."""

import logging
from datetime import date, timedelta

from django.db import transaction
from django.db.models import F, Max, QuerySet, Sum
from django.utils import timezone

from features.catalog import services as catalog
from features.catalog.models import Repository
from features.discovery import services as discovery
from features.discovery.models import ScanRun
from features.rising import _common, growth
from features.rising._common import (
    _CLASSIFY_BUSY,
    _OWNERS_AUTH,
    _OWNERS_BLOCKED,
    _OWNERS_STOPPED,
    _RETRY_MINUTES,
    _SCAN_FINISHED,
    _SCAN_UNFINISHED,
    CLASSIFY_BLOCKED_NOTE,
    EMPTY_WATCH_LIST_NOTE,
    OWNER_BUDGET_NOTE,
    OWNERS_BLOCKED_NOTE,
    REASON_BLOCKED,
    REASON_INTERRUPTED,
    REASON_STOPPED,
    REASON_VERIFY_AUTH,
    REASON_VERIFY_BLOCKED,
    UNREADABLE_HISTORY_NOTE,
    UNREADABLE_OWNER_NOTE,
    VERIFY_BUDGET_NOTE,
    DailySupersededError,
    _blocked_by_github,
    _busy_reason,
    _DailyStopRequestedError,
    _growth_facts,
    _HeartbeatSleep,
    _needs_new_scan,
    _owner_budget,
    _summary,
    _verify_budget,
)
from features.rising.models import DailyRun, DailyRunScan, RisingCheck, WatchQuery
from features.scoring import services as scoring
from features.scoring.services import REVIEW_FROM
from features.taxonomy import services as taxonomy
from integrations.github.client import GitHubClient, get_github_client
from integrations.github.errors import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubQueryError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubUnavailableError,
)
from integrations.github.pacing import (
    CallBudget,
    CallBudgetExhaustedError,
)
from integrations.github.schemas import StarHistory
from integrations.llm.client import get_llm_client, llm_configured
from integrations.llm.errors import LlmError

logger = logging.getLogger(__name__)


class _DailyRunner:
    """Một luồng chạy lượt. Mọi lần ghi đều kèm điều kiện "còn giữ lượt" (`runner_token`)."""

    def __init__(self, run_id: int, *, token: str) -> None:
        self.run_id = run_id
        self.token = token

    def run(self) -> None:
        """Làm tiếp từ bước đang dở.

        Xong một bước mới ghi bước kế: sập giữa chừng thì lần sau làm lại đúng bước đó.
        """
        run = self._check_in()
        if run.step == DailyRun.Step.RESCAN:
            if not self._rescan():
                return
            run = self._check_in(step=DailyRun.Step.SCREEN)
        if run.step == DailyRun.Step.SCREEN:
            self._screen()
            run = self._load()
        if run.step == DailyRun.Step.VERIFY:
            if not self._verify():
                return
            run = self._load()
        if run.step == DailyRun.Step.OWNERS:
            if not self._owners():
                return
            run = self._load()
        if run.step == DailyRun.Step.CLASSIFY:
            self._classify()
        self._report()

    # --- Bước 1: quét lại danh sách theo dõi -------------------------------------------------

    def _rescan(self) -> bool:
        """Mỗi truy vấn đang bật là một lần quét sâu, chạy lần lượt. `False` = lượt phải dừng."""
        watch_ids = list(WatchQuery.objects.filter(enabled=True).values_list("pk", flat=True))
        for index, watch_id in enumerate(watch_ids, start=1):
            run = self._check_in()
            if run.stop_requested:
                self.pause(DailyRun.PauseKind.STOPPED, REASON_STOPPED)
                return False
            # Đọc lại từng truy vấn: người dùng có thể xoá hoặc tắt nó trong lúc lượt đang chạy.
            watch = WatchQuery.objects.filter(pk=watch_id, enabled=True).first()
            if watch is None:
                continue
            logger.info(
                "Lượt hằng ngày %s: quét lại «%s» (%s/%s)",
                run.day,
                watch.query,
                index,
                len(watch_ids),
            )
            if not self._rescan_one(run, watch):
                return False
        self._note_left_behind()
        self._update(**self._totals(), heartbeat_at=timezone.now())
        return True

    def _rescan_one(self, run: DailyRun, watch: WatchQuery) -> bool:
        # Xét lần quét mới nhất của truy vấn: lần quét lỗi token / lỗi code được thay bằng lần mới.
        links = run.scans.select_related("scan_run").filter(watch_query=watch)
        link = links.order_by("-position", "-pk").first()
        if link is None or _needs_new_scan(link.scan_run):
            try:
                scan = self._start_scan(run, watch)
            except discovery.ScanAlreadyRunningError as exc:
                self.pause(DailyRun.PauseKind.RETRY_LATER, _busy_reason(exc.scan))
                return False
        else:
            scan = link.scan_run
            if scan.status in _SCAN_FINISHED:
                self._note(scan)  # đã xong ở lần chạy trước: không quét lại
                return True
            if scan.is_live:
                self.pause(DailyRun.PauseKind.RETRY_LATER, _busy_reason(scan))
                return False
            try:
                discovery.resume_scan(scan, extra_budget=0)
            except discovery.ScanAlreadyRunningError as exc:
                self.pause(DailyRun.PauseKind.RETRY_LATER, _busy_reason(exc.scan))
                return False
        discovery.execute_scan(scan.pk)
        self._check_in(**self._totals())
        scan.refresh_from_db()
        return self._after_child(scan)

    def _start_scan(self, run: DailyRun, watch: WatchQuery) -> ScanRun:
        request = discovery.ScanRequest(
            query=watch.query,
            min_stars=watch.min_stars,
            max_stars=watch.max_stars,
            created_from=None,
            created_to=None,
            budget=watch.budget,
            origin=ScanRun.Origin.DAILY,
        )
        # Lần quét và liên kết tới lượt ghi cùng lúc: app tắt giữa hai việc thì không để lại lần
        # quét mồ côi mà lượt không biết để nối lại.
        with transaction.atomic():
            scan = discovery.start_scan(request)
            # Lớn nhất + 1 chứ không phải số liên kết + 1: liên kết nào mất đi (lần quét bị xoá) thì
            # thứ tự mới vẫn không trùng thứ tự cũ.
            top = run.scans.aggregate(top=Max("position"))["top"] or 0
            DailyRunScan.objects.create(
                daily_run=run, watch_query=watch, scan_run=scan, position=top + 1
            )
        return scan

    def _after_child(self, scan: ScanRun) -> bool:
        """Xử lý kết quả lần quét con theo bảng ở mục 5 của thiết kế. `False` = lượt phải dừng."""
        if scan.status == ScanRun.Status.FAILED and scan.error_kind == ScanRun.ErrorKind.AUTH:
            # Token sai / hết quyền: truy vấn nào cũng sẽ hỏng như vậy → dừng cả lượt.
            self.fail(f"Truy vấn «{scan.query}» (lần quét #{scan.pk}): {scan.error_message}")
            return False
        if scan.status in _SCAN_FINISHED:
            self._note(scan)
            return True
        if scan.status == ScanRun.Status.PAUSED and scan.stop_reason == discovery.REASON_STOPPED:
            self.pause(DailyRun.PauseKind.STOPPED, REASON_STOPPED)
        elif scan.status == ScanRun.Status.PAUSED and _blocked_by_github(scan.stop_reason):
            reason = REASON_BLOCKED.format(
                query=scan.query, scan_id=scan.pk, minutes=_RETRY_MINUTES
            )
            self.pause(DailyRun.PauseKind.RETRY_LATER, reason)
        else:
            # Tạm dừng vì lý do khác (vd tiến trình khác coi nó là gián đoạn), hoặc luồng khác giữ.
            self.pause(DailyRun.PauseKind.INTERRUPTED, REASON_INTERRUPTED)
        return False

    def _note_left_behind(self) -> None:
        """Lần quét dở của truy vấn đã bị tắt hoặc xoá (lúc lượt đang dừng) → ghi lại, không bỏ rơi.

        Sau vòng quét lại, mọi truy vấn đang bật đều đã xong lần quét mới nhất của nó; lần quét còn
        dở chỉ có thể thuộc truy vấn không còn được quét nữa.
        """
        leftovers = DailyRunScan.objects.filter(
            daily_run_id=self.run_id, scan_run__status__in=_SCAN_UNFINISHED
        ).select_related("scan_run")
        for link in leftovers:
            scan = link.scan_run
            self._add_problem(
                f"Truy vấn «{scan.query}» (lần quét #{scan.pk}) đã tắt hoặc bị xoá khỏi danh sách "
                "theo dõi — lần quét còn dở, tiếp tục bằng tay ở trang lần quét đó được."
            )

    def _note(self, scan: ScanRun) -> None:
        """Lần quét con xong mà còn sót hoặc lỗi → ghi vào `problems` (ghi một lần dù chạy tiếp)."""
        if scan.status == ScanRun.Status.SUCCEEDED_PARTIAL:
            self._add_problem(
                f"Truy vấn «{scan.query}» (lần quét #{scan.pk}) còn sót: {scan.stop_reason}"
            )
        elif scan.status == ScanRun.Status.FAILED:
            self._add_problem(
                f"Truy vấn «{scan.query}» (lần quét #{scan.pk}) lỗi: {scan.error_message}"
            )

    # --- Bước 2: lọc thô bằng ảnh chụp (không tốn lượt gọi) -----------------------------------

    def _screen(self) -> None:
        """Ước lượng mức tăng 7 ngày của mọi repo vừa thấy; từ ngưỡng lọc thô trở lên là ứng viên.

        Ghi ứng viên và chuyển bước trong cùng một transaction; sập giữa chừng thì lần sau lọc lại
        từ đầu, xoá dòng ước lượng cũ của lượt trước khi ghi mới (không sinh dòng trùng).
        """
        run = self._check_in()
        now = timezone.now()
        # Ngày của lượt, không phải đồng hồ: lượt bấm lúc 23:50 mà lọc thô chạy sau 0:00 vẫn so mốc
        # đúng ngày của lượt.
        today = run.day
        scan_ids = list(
            DailyRunScan.objects.filter(daily_run_id=self.run_id).values_list(
                "scan_run_id", flat=True
            )
        )
        baselines = catalog.baseline_snapshots(today=today)
        # Fork, repo đã lưu trữ, repo từ 1.000 star không thể là rising star → không xét.
        seen = (
            discovery.repositories_seen_in(scan_ids)
            .filter(stars__lt=growth.RISING_MAX_STARS, is_fork=False, is_archived=False)
            .order_by("pk")
            .values_list("pk", "stars", "gh_created_at")
        )
        candidates: list[RisingCheck] = []
        insufficient = 0
        for repository_id, stars, created_at in seen.iterator():
            baseline = baselines.get(repository_id)
            estimate = growth.estimate_gain_7d(
                stars_now=stars,
                baseline=baseline,
                today=today,
                created_on=timezone.localdate(created_at),
            )
            if estimate is None:
                insufficient += 1
            elif estimate >= growth.CANDIDATE_MIN_ESTIMATE_7D:
                candidates.append(
                    RisingCheck(
                        daily_run_id=self.run_id,
                        repository_id=repository_id,
                        stars=stars,
                        source=(
                            RisingCheck.Source.AGE
                            if baseline is None
                            else RisingCheck.Source.SNAPSHOT
                        ),
                        gain_7d=estimate,
                        baseline_day=None if baseline is None else baseline.day,
                    )
                )
        with transaction.atomic():
            RisingCheck.objects.filter(daily_run_id=self.run_id).exclude(
                source=RisingCheck.Source.HISTORY
            ).delete()
            RisingCheck.objects.bulk_create(candidates)
            self._check_in(
                step=DailyRun.Step.VERIFY,
                candidate_count=len(candidates),
                insufficient_count=insufficient,
                window_end=growth.last_complete_utc_day(now),
            )
        logger.info(
            "Lượt hằng ngày #%s: lọc thô xong — %s ứng viên, %s repo chưa đủ dữ liệu",
            self.run_id,
            len(candidates),
            insufficient,
        )

    # --- Bước 3: xác minh bằng lịch sử star chính thức ---------------------------------------

    def _verify(self) -> bool:
        """Xác minh ứng viên bằng lịch sử star. `False` = lượt phải dừng (tạm dừng hoặc lỗi).

        Mỗi ứng viên chưa xác minh tốn một lượt gọi, ước lượng lớn trước, tới khi hết ngân sách.
        Dòng đã xác minh (kể cả ở lần chạy trước) không bao giờ bị gọi lại.
        """
        run = self._check_in()
        if run.verify_budget == 0:
            # Chốt ngân sách một lần lúc bắt đầu xác minh: chạy tiếp vẫn giữ ngân sách ban đầu.
            run = self._check_in(verify_budget=_verify_budget())
        pending = list(
            RisingCheck.objects.filter(daily_run_id=self.run_id)
            .exclude(source=RisingCheck.Source.HISTORY)
            .order_by("-gain_7d", "pk")
            .values_list("pk", flat=True)
        )
        if pending and not self._verify_rows(run, pending):
            return False
        self._check_in(step=DailyRun.Step.OWNERS)
        return True

    def _verify_rows(self, run: DailyRun, pending: list[int]) -> bool:
        window_end = run.window_end
        if window_end is None:
            raise RuntimeError(f"Lượt #{self.run_id} ở bước xác minh mà chưa chốt cửa sổ ngày UTC.")
        calls_before = run.verify_calls_used
        budget = CallBudget(max(0, run.verify_budget - calls_before))
        sleep = _HeartbeatSleep(self._beat_or_stop)
        try:
            with get_github_client(sleep=sleep, budget=budget) as github:
                for index, check_id in enumerate(pending, start=1):
                    self._beat_or_stop()
                    self._verify_one(
                        github,
                        check_id,
                        budget=budget,
                        calls_before=calls_before,
                        window_end=window_end,
                    )
                    logger.info(
                        "Lượt hằng ngày #%s: đã xét %s/%s ứng viên, lượt gọi xác minh %s/%s",
                        self.run_id,
                        index,
                        len(pending),
                        calls_before + budget.used,
                        run.verify_budget,
                    )
        except CallBudgetExhaustedError:
            left = (
                RisingCheck.objects.filter(daily_run_id=self.run_id)
                .exclude(source=RisingCheck.Source.HISTORY)
                .count()
            )
            self._add_problem(VERIFY_BUDGET_NOTE.format(count=left))
        except _DailyStopRequestedError:
            self.pause(DailyRun.PauseKind.STOPPED, REASON_STOPPED)
            return False
        except (GitHubRateLimitError, GitHubUnavailableError) as exc:
            logger.warning("Lượt hằng ngày #%s: GitHub chặn lúc xác minh: %r", self.run_id, exc)
            reason = REASON_VERIFY_BLOCKED.format(minutes=_RETRY_MINUTES)
            self.pause(DailyRun.PauseKind.RETRY_LATER, reason)
            return False
        except GitHubAuthError as exc:
            logger.warning("Lượt hằng ngày #%s: GitHub từ chối token: %r", self.run_id, exc)
            self.fail(REASON_VERIFY_AUTH.format(detail=exc))
            return False
        return True

    def _verify_one(
        self,
        github: GitHubClient,
        check_id: int,
        *,
        budget: CallBudget,
        calls_before: int,
        window_end: date,
    ) -> None:
        check = (
            RisingCheck.objects.select_related("repository")
            .filter(pk=check_id)
            .exclude(source=RisingCheck.Source.HISTORY)
            .first()
        )
        if check is None:
            return
        repository = check.repository
        try:
            history = self._fetch_history(
                github, repository.github_id, budget=budget, calls_before=calls_before
            )
        except GitHubNotFoundError:
            logger.info(
                "Lượt hằng ngày #%s: %s không còn trên GitHub (404) — bỏ khỏi danh sách xét",
                self.run_id,
                repository.full_name,
            )
            with transaction.atomic():
                self._update(heartbeat_at=timezone.now())  # còn giữ lượt mới được xoá
                RisingCheck.objects.filter(pk=check.pk).delete()
            return
        except (GitHubResponseError, GitHubQueryError) as exc:
            logger.warning(
                "Lượt hằng ngày #%s: lịch sử star của %s không đọc được: %r",
                self.run_id,
                repository.full_name,
                exc,
            )
            self._add_problem(UNREADABLE_HISTORY_NOTE.format(repo=repository.full_name, detail=exc))
            return
        self._save_history(check, history, window_end=window_end)

    def _fetch_history(
        self, github: GitHubClient, github_id: int, *, budget: CallBudget, calls_before: int
    ) -> StarHistory:
        try:
            return github.star_history(github_id)
        finally:
            # Ghi ngay sau mỗi lượt gọi, kể cả khi lỗi hay app sập: lượt gọi đã tiêu thì không được
            # "hoàn" vào ngân sách khi chạy tiếp. Không ném lỗi ở đây để không che lỗi gốc.
            self._owned().update(verify_calls_used=calls_before + budget.used)

    def _save_history(self, check: RisingCheck, history: StarHistory, *, window_end: date) -> None:
        gains = growth.growth_from_history(history, window_end=window_end)
        repository = check.repository
        age_days = (timezone.localdate() - timezone.localdate(repository.gh_created_at)).days
        flags = growth.warning_flags(
            series=gains.series, age_days=age_days, description=repository.description
        )
        with transaction.atomic():
            self._update(heartbeat_at=timezone.now())  # còn giữ lượt mới được ghi
            RisingCheck.objects.filter(pk=check.pk).update(
                source=RisingCheck.Source.HISTORY,
                gain_1d=gains.gain_1d,
                gain_7d=gains.gain_7d,
                gain_30d=gains.gain_30d,
                series=list(gains.series),
                window_end=window_end,
                is_rising=growth.is_rising(check.stars, gains.gain_7d),
                flags=[flag.value for flag in flags],
            )

    # --- Bước 4: lấy hồ sơ chủ của rising star (F-006) ------------------------------------------

    def _owners(self) -> bool:
        """Lấy hồ sơ chủ của rising star chưa có hồ sơ (hoặc hồ sơ quá 30 ngày). `False` = dừng.

        Chủ của repo đang bị nghi star giả (từ "Cần xem") được lấy trước: chỉ ở đó hồ sơ chủ mới đổi
        được kết luận, mà không token thì mỗi ngày chỉ lấy được 10 hồ sơ. Trong mỗi nhóm, repo tăng
        nhiều trước. Hồ sơ lưu ngay sau mỗi lượt gọi nên chạy tiếp không gọi lại; hết ngân sách chỉ
        ghi chú, không phải lỗi.
        """
        run = self._check_in()
        if run.owner_budget == 0:
            # Chốt ngân sách một lần lúc bắt đầu bước: chạy tiếp vẫn giữ ngân sách ban đầu.
            run = self._check_in(owner_budget=_owner_budget())
        checks = list(
            RisingCheck.objects.filter(daily_run_id=self.run_id, is_rising=True)
            .select_related("repository")
            .order_by("-gain_7d", "pk")
        )
        scores = scoring.score_repositories(
            [check.repository for check in checks],
            growth={check.repository_id: _growth_facts(check) for check in checks},
        )
        # Sắp ổn định: nhóm đang bị nghi lên trước, trong nhóm giữ thứ tự tăng nhiều trước.
        checks.sort(key=lambda check: scores[check.repository_id].suspicion.points < REVIEW_FROM)
        logins = [check.repository.owner_login for check in checks]
        pending = scoring.owners_to_fetch(logins, now=timezone.now())
        if pending:
            self._fetch_owners(run, pending)
        self._check_in(step=DailyRun.Step.CLASSIFY)
        return True

    def _fetch_owners(self, run: DailyRun, pending: list[str]) -> None:
        """Gọi GitHub lấy từng hồ sơ. Hỏng giữa chừng thì ghi chú rồi thôi — không chặn báo cáo.

        Bước này chỉ làm giàu dữ liệu (nguyên tắc 8): bấm Dừng, GitHub chặn hay từ chối token thì
        dừng gọi, ghi lại số chủ còn thiếu (lượt hôm sau lấy tiếp) và đi tiếp tới lập báo cáo —
        bước đó chỉ đọc CSDL nên xong ngay. Không để lượt kẹt ở đây rồi mất báo cáo khi hết ngày.
        """
        calls_before = run.owner_calls_used
        budget = CallBudget(max(0, run.owner_budget - calls_before))

        def record_calls() -> None:
            # Ghi sau mỗi lượt gọi, kể cả khi lỗi hay app sập: lượt đã tiêu không được "hoàn".
            self._owned().update(owner_calls_used=calls_before + budget.used)

        try:
            with get_github_client(sleep=_HeartbeatSleep(self._beat_or_stop), budget=budget) as gh:
                outcome = scoring.fetch_owner_profiles(
                    gh, pending, before_each=self._beat_or_stop, after_call=record_calls
                )
        except CallBudgetExhaustedError:
            left = len(scoring.owners_to_fetch(pending, now=timezone.now()))
            self._add_problem(OWNER_BUDGET_NOTE.format(count=left))
            return
        except _DailyStopRequestedError:
            self._note_owners_left(pending, _OWNERS_STOPPED)
            return
        except (GitHubRateLimitError, GitHubUnavailableError) as exc:
            logger.warning(
                "Lượt hằng ngày #%s: GitHub chặn lúc lấy hồ sơ chủ: %r", self.run_id, exc
            )
            self._note_owners_left(pending, _OWNERS_BLOCKED)
            return
        except GitHubAuthError as exc:
            logger.warning("Lượt hằng ngày #%s: GitHub từ chối token: %r", self.run_id, exc)
            self._note_owners_left(pending, _OWNERS_AUTH)
            return
        for login, detail in outcome.unreadable:
            self._add_problem(UNREADABLE_OWNER_NOTE.format(login=login, detail=detail))
        logger.info(
            "Lượt hằng ngày #%s: hồ sơ chủ repo — lấy %s, không còn tồn tại %s, lỗi %s",
            self.run_id,
            outcome.fetched,
            outcome.missing,
            len(outcome.unreadable),
        )

    def _note_owners_left(self, pending: list[str], detail: str) -> None:
        left = len(scoring.owners_to_fetch(pending, now=timezone.now()))
        self._add_problem(OWNERS_BLOCKED_NOTE.format(count=left, detail=detail))

    # --- Bước 5: phân loại repo của lượt bằng AI (F-010) ---------------------------------------

    def _classify(self) -> None:
        """Gắn nhãn cho repo của lượt (rising star trước). Chưa có khoá AI thì bỏ qua.

        Chỉ làm giàu dữ liệu (nguyên tắc 8): hỏng gì (9router tắt, khoá sai, bấm Dừng, đang có lần
        phân loại khác) cũng ghi chú rồi đi tiếp lập báo cáo. Hết ngân sách không phải lỗi: phần còn
        lại do việc định kỳ phân loại dần.
        """
        self._check_in()
        if llm_configured():
            self._classify_repos()
        self._check_in(step=DailyRun.Step.REPORT)

    def _classify_repos(self) -> None:
        in_run = Repository.objects.filter(rising_checks__daily_run_id=self.run_id)
        repos = taxonomy.repositories_needing_labels(among=in_run)
        if not repos:
            return
        order = list(
            RisingCheck.objects.filter(daily_run_id=self.run_id)
            .order_by("-is_rising", "-gain_7d", "pk")
            .values_list("repository_id", flat=True)
        )
        rank = {repository_id: index for index, repository_id in enumerate(order)}
        repos.sort(key=lambda repo: rank.get(repo.pk, len(rank)))
        try:
            classify_run = taxonomy.start_classify_run(taxonomy.Origin.DAILY)
        except taxonomy.ClassifyBusyError:
            self._add_problem(CLASSIFY_BLOCKED_NOTE.format(detail=_CLASSIFY_BUSY, count=len(repos)))
            return
        error = ""
        budget = CallBudget(_common.DAILY_RUN_CLASSIFY_CALLS)
        # Lúc chờ 9router vẫn ghi nhịp sống của cả lần phân loại lẫn lượt (và thấy nút Dừng).
        sleep = taxonomy.heartbeat_sleep(classify_run, also=self._beat_or_stop)
        try:
            with get_llm_client(sleep=sleep, budget=budget) as llm:
                taxonomy.classify(classify_run, repos, llm=llm, before_each=self._beat_or_stop)
        except CallBudgetExhaustedError:
            logger.info(
                "Lượt hằng ngày #%s: hết lượt phân loại trong lượt — phân loại dần sau", self.run_id
            )
        except _DailyStopRequestedError:
            error = _OWNERS_STOPPED
        except LlmError as exc:
            logger.warning("Lượt hằng ngày #%s: phân loại bằng AI hỏng: %r", self.run_id, exc)
            error = str(exc)
        except BaseException:
            # Lỗi bất ngờ (vd CSDL bị khoá) hay luồng mất quyền giữ lượt: ghi đúng là bị ngắt rồi
            # ném tiếp cho `execute_daily_run` xử lý — không ghi nhầm lần phân loại là "Xong".
            error = taxonomy.REASON_UNEXPECTED
            raise
        finally:
            taxonomy.finish_classify_run(classify_run, error=error)
            # Ghi cả khi lỗi; không ném lỗi ở đây để không che lỗi gốc.
            self._owned().update(ai_calls_used=F("ai_calls_used") + classify_run.calls_used)
        if error:
            left = len(taxonomy.repositories_needing_labels(among=in_run))
            self._add_problem(CLASSIFY_BLOCKED_NOTE.format(detail=error, count=left))

    def _beat_or_stop(self) -> None:
        """Ghi nhịp sống ở bước xác minh; người dùng đã bấm Dừng thì thôi, kể cả đang chờ GitHub."""
        if self._check_in().stop_requested:
            raise _DailyStopRequestedError

    # --- Bước 6: lập báo cáo, dọn dữ liệu cũ -------------------------------------------------

    def _report(self) -> None:
        """Ghi số rising / chưa xác minh, dọn dữ liệu quá hạn giữ, rồi kết thúc lượt.

        Dọn dữ liệu làm lại bao nhiêu lần cũng vậy: sập giữa chừng thì lần sau làm lại cả bước.
        """
        checks = RisingCheck.objects.filter(daily_run_id=self.run_id)
        self._check_in(
            rising_count=checks.filter(is_rising=True).count(),
            unverified_count=checks.exclude(source=RisingCheck.Source.HISTORY).count(),
        )
        now = timezone.now()
        snapshots = catalog.prune_snapshots(
            before=timezone.localdate(now) - timedelta(days=catalog.SNAPSHOT_RETENTION_DAYS)
        )
        results = discovery.prune_daily_results(
            before=now - timedelta(days=catalog.SNAPSHOT_RETENTION_DAYS)
        )
        # Điểm lưu sẵn cho trang Kho repo (QĐ-19): cả kho mỗi ngày ~3 giây, sau khi đã có số liệu
        # mới của các lần quét và hồ sơ chủ của lượt.
        scored = scoring.refresh_scores()
        logger.info("Lượt hằng ngày #%s: đã tính lại điểm lưu sẵn cho %s repo", self.run_id, scored)
        logger.info(
            "Lượt hằng ngày #%s: đã dọn %s ảnh chụp và %s dòng kết quả quét quá %s ngày",
            self.run_id,
            snapshots,
            results,
            catalog.SNAPSHOT_RETENTION_DAYS,
        )
        self._finish()

    # --- Kết cục -----------------------------------------------------------------------------

    def pause(self, kind: DailyRun.PauseKind, reason: str) -> None:
        """Tạm dừng lượt. Người dùng đã bấm Dừng thì ghi là "bấm Dừng": không tự chạy tiếp."""
        stop_requested = DailyRun.objects.filter(pk=self.run_id, stop_requested=True).exists()
        if stop_requested and kind != DailyRun.PauseKind.STOPPED:
            kind, reason = DailyRun.PauseKind.STOPPED, REASON_STOPPED
        self._write_outcome(
            status=DailyRun.Status.PAUSED,
            pause_kind=kind,
            stop_reason=reason,
            paused_at=timezone.now(),
        )

    def fail(self, error: str) -> None:
        self._write_outcome(
            status=DailyRun.Status.FAILED, error_message=error, finished_at=timezone.now()
        )

    def _finish(self) -> None:
        run = self._load()
        problems = list(run.problems)
        status = DailyRun.Status.SUCCEEDED_PARTIAL if problems else DailyRun.Status.SUCCEEDED
        reason = _summary(problems)
        if not problems and not run.scans.exists():
            # Danh sách theo dõi trống không làm sót gì → vẫn Xong, chỉ nhắc thêm truy vấn.
            reason = EMPTY_WATCH_LIST_NOTE
        self._write_outcome(
            status=status,
            stop_reason=reason,
            stop_requested=False,
            finished_at=timezone.now(),
        )

    def _write_outcome(self, **fields: object) -> None:
        """Ghi kết cục (kèm tổng lượt gọi) và nhả quyền giữ lượt; mất quyền rồi thì không ghi gì.

        Không ném `DailySupersededError`: hàm còn được gọi trong lúc xử lý Ctrl+C và lỗi bất ngờ.
        """
        self._owned().update(
            **self._totals(), **fields, runner_token="", heartbeat_at=timezone.now()
        )

    # --- Ghi có điều kiện ----------------------------------------------------------------------

    def _check_in(self, **fields: object) -> DailyRun:
        """Ghi nhịp sống (và `fields`) rồi đọc lại lượt; mất quyền giữ lượt thì rút lui."""
        self._update(**fields, heartbeat_at=timezone.now())
        return self._load()

    def _add_problem(self, note: str) -> None:
        problems = list(self._load().problems)
        if note not in problems:
            self._update(problems=[*problems, note])

    def _totals(self) -> dict[str, int]:
        """Tổng lượt gọi Search và số repo mới của các lần quét con.

        Luôn cộng lại từ đầu thay vì cộng dồn: chạy tiếp bao nhiêu lần cũng không bị cộng trùng.
        """
        sums = DailyRunScan.objects.filter(daily_run_id=self.run_id).aggregate(
            calls=Sum("scan_run__api_calls_used"), created=Sum("scan_run__created_count")
        )
        return {"search_calls_used": sums["calls"] or 0, "new_repo_count": sums["created"] or 0}

    def _load(self) -> DailyRun:
        run = self._owned().first()
        if run is None:
            raise DailySupersededError
        return run

    def _update(self, **fields: object) -> None:
        if not self._owned().update(**fields):
            raise DailySupersededError

    def _owned(self) -> QuerySet[DailyRun]:
        return DailyRun.objects.filter(
            pk=self.run_id, runner_token=self.token, status=DailyRun.Status.RUNNING
        )
