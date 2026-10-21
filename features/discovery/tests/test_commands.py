"""Lệnh `manage.py scan`: cùng nghiệp vụ với trang web; dùng cho lịch chạy và để agent tự kiểm."""

from io import StringIO

import pytest
import respx
from django.core.management import CommandError, call_command

from features.discovery.tests.conftest import REAL_TOP_REPOS, SEARCH_URL

pytestmark = pytest.mark.django_db


def test_scan_command_prints_summary_and_top_repositories(github_search: respx.Route) -> None:
    out = StringIO()

    call_command("scan", "topic:ai-agent", stdout=out)

    text = out.getvalue()
    assert "lấy 3/40194" in text
    assert "mới 3" in text
    assert all(name in text for name in REAL_TOP_REPOS)


def test_scan_command_fails_loudly_when_github_fails(http_mock: respx.MockRouter) -> None:
    http_mock.get(SEARCH_URL).respond(401, json={"message": "Bad credentials"})

    with pytest.raises(CommandError, match="GITHUB_TOKEN"):
        call_command("scan", "topic:ai-agent", stdout=StringIO())


def test_scan_command_rejects_blank_query() -> None:
    with pytest.raises(CommandError, match="Hãy nhập truy vấn"):
        call_command("scan", "   ", stdout=StringIO())
