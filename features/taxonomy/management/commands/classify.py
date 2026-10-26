"""Lệnh `manage.py classify`: phân loại bù cả kho bằng AI (lần đầu, hoặc sau khi đổi bộ nhóm).

uv run python manage.py classify                    # mọi repo chưa có nhãn (tối đa 1.000 lượt gọi)
uv run python manage.py classify --budget 50        # chỉ tiêu tối đa 50 lượt gọi AI
uv run python manage.py classify --reclassify       # gắn lại nhãn do prompt / bộ nhóm cũ

Lớp mỏng: kiểm tham số → `taxonomy.services.classify_catalog` → in tiến độ và tổng kết.
"""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import formats

from features.taxonomy import services
from integrations.llm.client import llm_configured
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
            help="Gắn lại cả nhãn do prompt / bộ nhóm cũ, và thử lại repo đang nghỉ vì AI bỏ sót.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not llm_configured():
            raise CommandError(
                "Chưa có LLM_API_KEY trong .env — lấy khoá trong trang quản lý 9router rồi điền "
                "vào."
            )
        budget: int = options["budget"]
        limit: int | None = options["limit"]
        if budget < 1 or (limit is not None and limit < 1):
            raise CommandError("--budget và --limit phải từ 1 trở lên.")
        started = time.monotonic()
        try:
            report = services.classify_catalog(
                budget=budget,
                limit=limit,
                reclassify=options["reclassify"],
                on_progress=self._progress,
                on_retry=lambda count: self.stdout.write(f"Thử lại {_n(count)} repo AI bỏ sót."),
            )
        except services.ClassifyBusyError as exc:
            raise CommandError(f"{exc} Chờ lần đó xong rồi chạy lại.") from exc
        except LlmError as exc:
            raise CommandError(f"Dừng phân loại: {exc}") from exc
        except KeyboardInterrupt:
            self.stdout.write("Đã dừng (Ctrl+C) — phần đã phân loại vẫn được lưu.")
            raise
        self.stdout.write(f"Cần phân loại: {_n(report.needed)} repo.")
        if report.run is None:
            return
        if report.stopped:
            self.stdout.write(report.stopped)
        run = report.run
        missing = max(0, report.needed - run.classified_count)
        self.stdout.write(
            f"Xong: {_n(run.classified_count)} repo có nhãn, {_n(missing)} repo AI bỏ sót"
            f" · {run.calls_used} lượt gọi AI · {_n(run.prompt_tokens)} token vào,"
            f" {_n(run.completion_tokens)} token ra · {(time.monotonic() - started) / 60:.1f} phút."
        )

    def _progress(self, done: int, total: int) -> None:
        self.stdout.write(f"[{done}/{total}]")
        self.stdout.flush()


def _n(value: int) -> str:
    return formats.number_format(value, force_grouping=True)
