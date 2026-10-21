"""Hàm dựng dữ liệu mẫu dùng chung cho test (không dùng trong code chạy thật)."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from integrations.github.schemas import GitHubRepo

_BASE_REPO = GitHubRepo(
    github_id=1010681419,
    full_name="shareAI-lab/learn-claude-code",
    html_url="https://github.com/shareAI-lab/learn-claude-code",
    description="Bash is all you need",
    language="Python",
    topics=("agent", "claude-code"),
    stars=78952,
    forks=12625,
    owner_login="shareAI-lab",
    owner_type="Organization",
    license_spdx="MIT",
    is_fork=False,
    is_archived=False,
    created_at=datetime(2025, 6, 29, 15, 34, 15, tzinfo=UTC),
    pushed_at=datetime(2026, 9, 28, 13, 49, 16, tzinfo=UTC),
)


def make_github_repo(**overrides: Any) -> GitHubRepo:
    """Một repo GitHub hợp lệ; truyền tham số để đổi trường cần cho test."""
    return replace(_BASE_REPO, **overrides)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(relative_path: str) -> dict[str, Any]:
    """Đọc phản hồi THẬT đã lưu của dịch vụ ngoài, ví dụ "github/search_repositories.json"."""
    data: dict[str, Any] = json.loads((FIXTURES_DIR / relative_path).read_text(encoding="utf-8"))
    return data
