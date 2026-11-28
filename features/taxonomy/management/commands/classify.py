"""Lệnh `manage.py classify`: phân loại bù cả kho bằng AI (lần đầu, hoặc sau khi đổi bộ nhóm).

uv run python manage.py classify                    # mọi repo chưa có nhãn (tối đa 1.000 lượt gọi)
uv run python manage.py classify --budget 50        # chỉ tiêu tối đa 50 lượt gọi AI
uv run python manage.py classify --reclassify       # gắn lại nhãn do prompt / bộ nhóm cũ
uv run python manage.py classify --rules            # gắn nhãn bằng luật từ khoá (không cần AI)
uv run python manage.py classify --compare-rules    # đo luật từ khoá so với nhãn AI (chỉ đọc)

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

        parser.add_argument(
            "--rules",
            action="store_true",
            help="Gắn nhãn bằng luật từ khoá cho repo chưa có nhãn. Không gọi AI, không ghi đè AI.",
        )
        parser.add_argument(
            "--compare-rules",
            action="store_true",
            help="Chỉ đo: luật từ khoá khớp nhãn AI đang lưu tới đâu. Không gọi AI, không ghi gì.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["compare_rules"]:
            self._compare_rules()
            return
        if options["rules"]:
            self._label_by_rules()
            return
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
        # Dừng vì hết ngân sách thì phần lớn repo còn thiếu là chưa tới lượt, không phải AI bỏ sót.
        missing_text = (
            f"{_n(missing)} repo chưa có nhãn — chạy lại lệnh để làm tiếp"
            if report.stopped
            else f"{_n(missing)} repo AI bỏ sót"
        )
        self.stdout.write(
            f"Xong: {_n(run.classified_count)} repo có nhãn, {missing_text}"
            f" · {run.calls_used} lượt gọi AI · {_n(run.prompt_tokens)} token vào,"
            f" {_n(run.completion_tokens)} token ra · {(time.monotonic() - started) / 60:.1f} phút."
        )

    def _label_by_rules(self) -> None:
        by_rules = services.classify_catalog_by_rules()
        self.stdout.write(
            f"Luật đã xét {_n(by_rules.examined)} repo: gắn nhãn {_n(by_rules.labelled)},"
            f" gỡ nhãn không còn khớp {_n(by_rules.removed)},"
            f" không xếp được {_n(by_rules.unplaced)}."
        )

    def _compare_rules(self) -> None:
        report = services.compare_rules_with_ai()
        share = _percent(report.unplaced / report.compared if report.compared else None)
        self.stdout.write(
            f"So với nhãn AI của {_n(report.compared)} repo; luật không xếp được"
            f" {_n(report.unplaced)} repo ({share})."
        )
        self.stdout.write(
            f"{'nhóm':<14}{'tên':<50}{'AI gắn':>9}{'luật gắn':>10}{'trùng':>8}"
            f"{'bắt được':>10}{'đúng':>7}"
        )
        for group in report.groups:
            self.stdout.write(
                f"{group.code:<14}{group.name[:48]:<50}{group.ai:>9}{group.rule:>10}{group.both:>8}"
                f"{_percent(group.recall):>10}{_percent(group.precision):>7}"
            )

    def _progress(self, done: int, total: int) -> None:
        self.stdout.write(f"[{done}/{total}]")
        self.stdout.flush()


def _n(value: int) -> str:
    return formats.number_format(value, force_grouping=True)


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"
