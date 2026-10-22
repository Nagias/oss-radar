"""Migration dữ liệu: 16 truy vấn theo dõi gợi ý (thiết kế F-005 mục 2), đúng thứ tự, đúng nhãn."""

import importlib

import pytest
from django.apps import apps

from features.rising.models import WatchQuery

pytestmark = pytest.mark.django_db

seed_migration = importlib.import_module("features.rising.migrations.0002_seed_watch_queries")

SUGGESTED = [
    ("AI Agent", "topic:ai-agent"),
    ("AI Agent", "topic:ai-agents"),
    ("AI Agent", "topic:agentic-ai"),
    ("AI Agent", "topic:mcp-server"),
    ("Vibe code", "topic:vibe-coding"),
    ("Vibe code", "topic:claude-code"),
    ("Video AI", "topic:ai-video"),
    ("Video AI", "topic:text-to-video"),
    ("Video AI", "topic:video-generation"),
    ("Ảnh AI", "topic:comfyui"),
    ("Ảnh AI", "topic:image-generation"),
    ("Marketing", "topic:marketing-automation"),
    ("Marketing", "topic:ai-marketing"),
    ("Marketing", "topic:seo"),
    ("Doanh nghiệp một người", "topic:solopreneur"),
    ("Doanh nghiệp một người", "topic:indie-hacker"),
]


def test_seed_creates_sixteen_suggested_watch_queries_in_order() -> None:
    rows = list(WatchQuery.objects.all())

    assert [(row.label, row.query) for row in rows] == SUGGESTED
    assert [row.position for row in rows] == list(range(1, 17))
    assert {(row.min_stars, row.max_stars, row.budget, row.enabled) for row in rows} == {
        (10, None, 300, True)
    }


def test_seed_run_again_does_not_duplicate() -> None:
    seed_migration.seed_watch_queries(apps, None)

    assert WatchQuery.objects.count() == 16
