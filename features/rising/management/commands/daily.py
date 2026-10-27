"""`uv run python manage.py daily` — chạy đúng lượt quét hằng ngày của hôm nay, in tóm tắt.

Bỏ qua giờ hẹn 7:00; cùng nghiệp vụ với nút "Chạy ngay" trên trang Rising star. Hôm nay đã xong thì
từ chối (mỗi ngày một báo cáo); đang Tạm dừng hoặc Lỗi thì làm tiếp từ bước dở. Tiến độ từng bước
hiện ở log (stderr). Có thể gắn Task Scheduler của Windows để chạy mỗi ngày khi không mở app.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from features.rising import services
from features.rising.models import DailyRun

TOP_TO_PRINT = 10


class Command(BaseCommand):
    help = "Chạy lượt quét hằng ngày của hôm nay: quét lại danh sách theo dõi, xác minh, báo cáo."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            run = services.prepare_daily_run()
        except services.DailyRunBlockedError as exc:
            raise CommandError(str(exc)) from exc
        services.execute_daily_run(run.pk)
        run.refresh_from_db()
        if run.status == DailyRun.Status.FAILED:
            raise CommandError(f"Lượt hằng ngày {run.day:%d/%m/%Y} lỗi: {run.error_message}")
        self._print_summary(run)

    def _print_summary(self, run: DailyRun) -> None:
        self.stdout.write(f"Lượt hằng ngày {run.day:%d/%m/%Y} — {run.get_status_display()}.")
        verify = f"{run.verify_calls_used}/{run.verify_budget}"
        owners = f"{run.owner_calls_used}/{run.owner_budget}"
        self.stdout.write(
            f"Lượt gọi: Search {run.search_calls_used}, xác minh {verify}, hồ sơ chủ {owners},"
            f" AI {run.ai_calls_used}."
        )
        for note in run.stop_reason.splitlines():
            self.stdout.write(f"Ghi chú: {note}")
        if run.status == DailyRun.Status.PAUSED:
            self.stdout.write("Lượt chưa xong — chạy lại `manage.py daily` để làm tiếp từ bước dở.")
            return
        report = services.daily_report(run)
        self.stdout.write(f"Rising star: {run.rising_count}")
        for row in report.rising[:TOP_TO_PRINT]:
            gain = _vietnamese_number(row.check.gain_7d)
            stars = _vietnamese_number(row.check.stars)
            self.stdout.write(
                f"  {'+' + gain:>8} sao/7 ngày  {row.repository.full_name} ({stars} sao)"
            )


def _vietnamese_number(value: int) -> str:
    """255.793 kiểu Việt Nam (dấu chấm ngăn nghìn), như lệnh `scan`."""
    return f"{value:,}".replace(",", ".")
