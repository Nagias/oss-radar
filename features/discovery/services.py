"""Nghiệp vụ của tính năng Quét: gọi GitHub → ghi kho không trùng → lưu lần quét và kết quả.

View và lệnh dòng lệnh chỉ gọi các hàm ở đây; không chứa logic riêng.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from features.catalog.services import upsert_repositories
from features.discovery.models import ScanResult, ScanRun
from integrations.github.client import get_github_client
from integrations.github.errors import (
    GitHubAuthError,
    GitHubError,
    GitHubQueryError,
    GitHubRateLimitError,
    GitHubUnavailableError,
)

logger = logging.getLogger(__name__)

# Lời giải thích cho người dùng theo từng loại lỗi GitHub; chi tiết kỹ thuật được nối thêm phía sau.
_FAILURE_REASONS: tuple[tuple[type[GitHubError], str], ...] = (
    (
        GitHubRateLimitError,
        "GitHub báo đã hết lượt gọi API. Chờ một lúc rồi quét lại "
        "(điền GITHUB_TOKEN vào .env để có nhiều lượt hơn).",
    ),
    (GitHubAuthError, "GitHub từ chối token. Kiểm tra lại GITHUB_TOKEN trong .env."),
    (GitHubQueryError, "GitHub không chấp nhận truy vấn này. Kiểm tra lại cú pháp tìm kiếm."),
    (GitHubUnavailableError, "Không gọi được GitHub hoặc GitHub đang lỗi. Thử lại sau."),
)
_UNKNOWN_GITHUB_REASON = "GitHub trả về dữ liệu không đọc được."
_UNEXPECTED_REASON = "Lỗi không mong đợi trong lúc quét — xem log của máy chủ."


def run_scan(query: str) -> ScanRun:
    """Quét GitHub theo truy vấn và ghi kết quả vào kho.

    Lỗi từ GitHub → lần quét có trạng thái "Lỗi" kèm lý do, không ném lỗi ra ngoài.
    Lỗi khác (lỗi lập trình) → vẫn ghi "Lỗi" rồi ném tiếp để không bị giấu đi.
    """
    # DEBT(D-003): quét chạy đồng bộ ngay trong lời gọi (web phải chờ); chưa có việc nền.
    scan = ScanRun.objects.create(query=query)
    scan.status = ScanRun.Status.RUNNING
    scan.started_at = timezone.now()
    scan.save(update_fields=["status", "started_at"])
    try:
        _fetch_and_store(scan)
    except GitHubError as exc:
        logger.warning("Lần quét #%s lỗi từ GitHub: %r", scan.pk, exc)
        _mark_failed(scan, f"{_reason_for(exc)} (Chi tiết: {exc})")
    except Exception:
        logger.exception("Lần quét #%s gặp lỗi không mong đợi", scan.pk)
        _mark_failed(scan, _UNEXPECTED_REASON)
        raise
    return scan


def recent_scans(limit: int = 10) -> QuerySet[ScanRun]:
    """Các lần quét mới nhất trước."""
    return ScanRun.objects.all()[:limit]


def scan_results(scan: ScanRun) -> QuerySet[ScanResult]:
    """Kết quả của một lần quét, sắp theo star giảm dần."""
    return scan.results.select_related("repository").order_by(
        "-repository__stars", "repository__full_name"
    )


def _fetch_and_store(scan: ScanRun) -> None:
    with get_github_client() as github:
        # DEBT(D-004): chỉ lấy trang đầu (tối đa SCAN_PAGE_SIZE repo nhiều star nhất).
        page = github.search_repositories(scan.query, per_page=settings.SCAN_PAGE_SIZE)
    with transaction.atomic():
        outcomes = upsert_repositories(page.items, seen_at=timezone.now())
        ScanResult.objects.bulk_create(
            ScanResult(scan_run=scan, repository=o.repository, is_new=o.created) for o in outcomes
        )
        scan.total_count = page.total_count
        scan.fetched_count = len(outcomes)
        scan.created_count = sum(1 for o in outcomes if o.created)
        scan.updated_count = scan.fetched_count - scan.created_count
        scan.status = ScanRun.Status.SUCCEEDED
        scan.finished_at = timezone.now()
        scan.save()


def _mark_failed(scan: ScanRun, reason: str) -> None:
    scan.status = ScanRun.Status.FAILED
    scan.error_message = reason
    scan.finished_at = timezone.now()
    scan.save(update_fields=["status", "error_message", "finished_at"])


def _reason_for(exc: GitHubError) -> str:
    for error_type, reason in _FAILURE_REASONS:
        if isinstance(exc, error_type):
            return reason
    return _UNKNOWN_GITHUB_REASON
