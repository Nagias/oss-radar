"""Lệnh `manage.py scan`: cùng nghiệp vụ với trang web; dùng để chạy tay và để agent tự kiểm."""

from collections.abc import Callable
from datetime import date
from io import StringIO
from typing import Any

import pytest
import respx
from django.core.management import CommandError, call_command

from features.discovery import services
from features.discovery.models import ScanRun
from features.discovery.tests.conftest import (
    DEFAULT_REQUEST,
    REAL_TOP_REPOS,
    SEARCH_URL,
    run_scan_now,
)
from tests.fakes import FakeGitHubSearch, make_search_items

pytestmark = pytest.mark.django_db


def test_scan_command_prints_coverage_and_top_repositories(github_search: respx.Route) -> None:
    out = StringIO()

    call_command("scan", "topic:ai-agent", "--min-stars", "0", "--budget", "1", stdout=out)

    text = out.getvalue()
    assert "lấy 3/40194" in text
    assert "độ phủ" in text
    assert "1/1 lượt gọi" in text
    assert all(name in text for name in REAL_TOP_REPOS)


def test_scan_command_resume(
    use_fake_github: Callable[[list[dict[str, Any]]], FakeGitHubSearch],
) -> None:
    items = make_search_items(
        2500, start=date(2025, 1, 1), end=date(2026, 6, 30), stars=lambda i: i % 3000
    )
    use_fake_github(items)
    partial = run_scan_now(created_from=date(2025, 1, 1), created_to=date(2026, 6, 30), budget=5)
    out = StringIO()

    call_command("scan", "--resume", str(partial.pk), "--extra-budget", "1000", stdout=out)

    partial.refresh_from_db()
    assert partial.status == ScanRun.Status.SUCCEEDED
    assert "lấy 2500/2500" in out.getvalue()


def test_scan_command_rejects_forbidden_qualifier() -> None:
    with pytest.raises(CommandError, match="stars:"):
        call_command("scan", "topic:ai-agent stars:>5", stdout=StringIO())


def test_scan_command_rejects_blank_query() -> None:
    with pytest.raises(CommandError, match="Hãy nhập truy vấn"):
        call_command("scan", "   ", stdout=StringIO())


def test_scan_command_needs_query_or_resume() -> None:
    with pytest.raises(CommandError, match="--resume"):
        call_command("scan", stdout=StringIO())


def test_scan_command_fails_loudly_on_auth_error(http_mock: respx.MockRouter) -> None:
    http_mock.get(SEARCH_URL).respond(401, json={"message": "Bad credentials"})

    with pytest.raises(CommandError, match="GITHUB_TOKEN"):
        call_command("scan", "topic:ai-agent", stdout=StringIO())


def test_scan_command_resume_unknown_scan() -> None:
    with pytest.raises(CommandError, match="#999"):
        call_command("scan", "--resume", "999", stdout=StringIO())


def test_scan_command_refused_while_another_scan_is_live() -> None:
    live = services.start_scan(DEFAULT_REQUEST)

    with pytest.raises(CommandError, match=f"#{live.pk}"):
        call_command("scan", "topic:ai-agent", stdout=StringIO())


def test_scan_command_cannot_resume_finished_scan(github_search: respx.Route) -> None:
    scan = run_scan_now()
    ScanRun.objects.filter(pk=scan.pk).update(status=ScanRun.Status.SUCCEEDED)

    with pytest.raises(CommandError, match="không ở trạng thái"):
        call_command("scan", "--resume", str(scan.pk), stdout=StringIO())
