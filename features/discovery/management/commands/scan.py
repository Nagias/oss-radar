"""`uv run python manage.py scan "<truy vấn>"` — chạy thật một lần quét ở tiền cảnh, in tiến độ.

Cùng nghiệp vụ và cùng form kiểm tra với trang web. Ví dụ:
    manage.py scan "topic:ai-video" --min-stars 10 --budget 300
    manage.py scan --resume 12 --extra-budget 300
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.forms import Form

from features.discovery import services
from features.discovery.forms import DEFAULT_BUDGET, DEFAULT_MIN_STARS, ResumeForm, ScanForm
from features.discovery.models import ScanRun

TOP_TO_PRINT = 10


class Command(BaseCommand):
    help = "Quét GitHub theo truy vấn (chia lát, trong ngân sách), lưu vào kho không trùng."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("query", nargs="?", help="Truy vấn theo cú pháp tìm kiếm của GitHub")
        parser.add_argument("--min-stars", type=int, default=DEFAULT_MIN_STARS)
        parser.add_argument("--max-stars", type=int)
        parser.add_argument("--from", dest="created_from", help="Tạo từ ngày, YYYY-MM-DD")
        parser.add_argument("--to", dest="created_to", help="Tạo đến ngày, YYYY-MM-DD")
        parser.add_argument(
            "--budget", type=int, default=DEFAULT_BUDGET, help="1, 50, 300 hoặc 1000"
        )
        parser.add_argument("--resume", type=int, metavar="ID", help="Tiếp tục lần quét có số ID")
        parser.add_argument("--extra-budget", type=int, default=DEFAULT_BUDGET)

    def handle(self, *args: Any, **options: Any) -> None:
        scan = self._resume(options) if options["resume"] is not None else self._start(options)
        services.execute_scan(scan.pk)
        scan.refresh_from_db()
        if scan.status == ScanRun.Status.FAILED:
            raise CommandError(f"Lần quét #{scan.pk} lỗi: {scan.error_message}")
        self._print_summary(scan)

    def _start(self, options: dict[str, Any]) -> ScanRun:
        if options["query"] is None:
            raise CommandError('Cần truy vấn, ví dụ: scan "topic:ai-agent" — hoặc --resume ID.')
        form = ScanForm(
            data={
                "query": options["query"],
                "min_stars": options["min_stars"],
                "max_stars": options["max_stars"] if options["max_stars"] is not None else "",
                "created_from": options["created_from"] or "",
                "created_to": options["created_to"] or "",
                "budget": options["budget"],
            }
        )
        _require_valid(form)
        try:
            return services.start_scan(form.to_request())
        except services.ScanAlreadyRunningError as exc:
            raise CommandError(str(exc)) from exc

    def _resume(self, options: dict[str, Any]) -> ScanRun:
        scan_id = options["resume"]
        scan = ScanRun.objects.filter(pk=scan_id).first()
        if scan is None:
            raise CommandError(f"Không có lần quét #{scan_id}.")
        form = ResumeForm(data={"extra_budget": options["extra_budget"]})
        _require_valid(form)
        try:
            return services.resume_scan(scan, extra_budget=form.cleaned_data["extra_budget"])
        except (services.ScanAlreadyRunningError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

    def _print_summary(self, scan: ScanRun) -> None:
        # DEBT(D-008): GitHub chưa trả tổng (total_count None) thì dòng tóm tắt in "0/None".
        coverage = "—" if scan.coverage_percent is None else f"{scan.coverage_percent}%"
        self.stdout.write(
            f"Lần quét #{scan.pk} — {scan.get_status_display()}: lấy {scan.fetched_count}/"
            f"{scan.total_count} repo GitHub báo có (độ phủ {coverage}); mới {scan.created_count}, "
            f"đã có {scan.updated_count}; dùng {scan.api_calls_used}/{scan.budget} lượt gọi."
        )
        if scan.stop_reason:
            self.stdout.write(f"Ghi chú: {scan.stop_reason}")
        for result in services.scan_results(scan)[:TOP_TO_PRINT]:
            repo = result.repository
            stars = f"{repo.stars:>9,}".replace(",", ".")  # 255.793 kiểu Việt Nam
            tag = " (mới)" if result.is_new else ""
            self.stdout.write(f"  {stars} sao  {repo.full_name}{tag}")


def _require_valid(form: Form) -> None:
    if form.is_valid():
        return
    messages = [str(message) for errors in form.errors.values() for message in errors]
    raise CommandError(" ".join(messages))
