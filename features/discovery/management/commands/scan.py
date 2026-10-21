"""`uv run python manage.py scan "<truy vấn>"` — chạy thật luồng F-001 từ dòng lệnh."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from features.discovery import services
from features.discovery.forms import ScanForm
from features.discovery.models import ScanRun

TOP_TO_PRINT = 10


class Command(BaseCommand):
    help = "Quét GitHub theo một truy vấn, lưu vào kho (không trùng) và in tóm tắt."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("query", help="Truy vấn theo cú pháp tìm kiếm của GitHub")

    def handle(self, *args: Any, **options: Any) -> None:
        form = ScanForm(data={"query": options["query"]})
        if not form.is_valid():
            raise CommandError(" ".join(str(message) for message in form.errors["query"]))

        scan = services.run_scan(form.cleaned_data["query"])
        if scan.status == ScanRun.Status.FAILED:
            raise CommandError(f"Lần quét #{scan.pk} lỗi: {scan.error_message}")

        self.stdout.write(
            f"Lần quét #{scan.pk} xong: lấy {scan.fetched_count}/{scan.total_count} repo "
            f"GitHub báo có; mới {scan.created_count}, đã có {scan.updated_count}."
        )
        for result in services.scan_results(scan)[:TOP_TO_PRINT]:
            repo = result.repository
            tag = " (mới)" if result.is_new else ""
            stars = f"{repo.stars:>9,}".replace(",", ".")  # 255.793 kiểu Việt Nam
            self.stdout.write(f"  {stars} sao  {repo.full_name}{tag}")
