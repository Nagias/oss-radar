"""Lệnh `manage.py classify`: phân loại bù cả kho bằng AI (lần đầu, hoặc sau khi đổi bộ nhóm).

uv run python manage.py classify                    # mọi repo chưa có nhãn (tối đa 1.000 lượt gọi)
uv run python manage.py classify --budget 50        # chỉ tiêu tối đa 50 lượt gọi AI
uv run python manage.py classify --reclassify       # gắn lại nhãn do prompt / bộ nhóm cũ
"""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import formats

from features.taxonomy import services
from features.taxonomy.models import ClassifyRun
from integrations.github.pacing import CallBudget, CallBudgetExhaustedError
from integrations.llm.client import get_llm_client, llm_configured
from integrations.llm.errors import LlmError

DEFAULT_BUDGET = 1000  # cả kho ~32.000 repo ≈ 810 lượt (40 repo mỗi lượt)


class Command(BaseCommand):
    help = "Phân loại repo trong kho bằng AI (Gemini qua 9router) theo bộ nhóm categories.toml."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--budget",
            type=int,
            default=DEFAULT_BUDGET,
            help=f"Số lượt gọi AI tối đa (mặc định {DEFAULT_BUDGET}).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Chỉ phân loại tối đa N repo (nhiều star trước).",
        )
        parser.add_argument(
            "--reclassify",
            action="store_true",
            help="Gắn lại cả nhãn do prompt / bộ nhóm phiên bản cũ gắn.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not llm_configured():
            raise CommandError(
                "Chưa có LLM_API_KEY trong .env — lấy khoá trong trang quản lý 9router rồi điền "
                "vào."
            )
        budget: int = options["budget"]
        if budget < 1:
            raise CommandError("--budget phải từ 1 trở lên.")
        repos = services.repositories_needing_labels(reclassify=options["reclassify"])
        if options["limit"] is not None:
            repos = repos[: options["limit"]]
        self.stdout.write(f"Cần phân loại: {_n(len(repos))} repo.")
        if not repos:
            return
        try:
            run = services.start_classify_run(ClassifyRun.Origin.COMMAND)
        except services.ClassifyBusyError as exc:
            raise CommandError(f"{exc} Chờ lần đó xong rồi chạy lại.") from exc
        started = time.monotonic()
        error = ""
        try:
            with get_llm_client(budget=CallBudget(budget)) as llm:
                services.classify(
                    run,
                    repos,
                    llm=llm,
                    after_batch=lambda done: self._progress(run, done, len(repos)),
                )
        except CallBudgetExhaustedError:
            error = f"Hết ngân sách {budget} lượt gọi."
            self.stdout.write(error)
        except LlmError as exc:
            services.finish_classify_run(run, error=str(exc))
            raise CommandError(f"Dừng phân loại: {exc}") from exc
        except KeyboardInterrupt:
            services.finish_classify_run(run, error="Dừng tay (Ctrl+C).")
            self.stdout.write("Đã dừng (Ctrl+C) — phần đã phân loại vẫn được lưu.")
            raise
        services.finish_classify_run(run, error=error)
        self._summary(
            run, missing=len(repos) - run.classified_count, seconds=time.monotonic() - started
        )

    def _progress(self, run: ClassifyRun, done: int, total: int) -> None:
        run.refresh_from_db()
        self.stdout.write(
            f"[{done}/{total}] {_n(run.classified_count)} repo có nhãn · {run.calls_used} lượt gọi"
            f" · {_n(run.prompt_tokens + run.completion_tokens)} token"
        )

    def _summary(self, run: ClassifyRun, *, missing: int, seconds: float) -> None:
        self.stdout.write(
            f"Xong: {_n(run.classified_count)} repo có nhãn, {_n(max(0, missing))} repo AI bỏ sót"
            f" · {run.calls_used} lượt gọi AI · {_n(run.prompt_tokens)} token vào,"
            f" {_n(run.completion_tokens)} token ra · {seconds / 60:.1f} phút."
        )


def _n(value: int) -> str:
    return formats.number_format(value, force_grouping=True)
