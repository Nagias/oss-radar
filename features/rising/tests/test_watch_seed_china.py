"""Migration dữ liệu: 10 truy vấn theo dõi tiếng Trung (thiết kế bộ luật 2026-11-28, Luật D)."""

import importlib

import pytest
from django.apps import apps

from features.rising.models import WatchQuery

pytestmark = pytest.mark.django_db

seed_migration = importlib.import_module("features.rising.migrations.0006_seed_china_watch_queries")

CHINA = [
    ("Trung Quốc · AI Agent", "智能体"),
    ("Trung Quốc · AI Agent", "大模型"),
    ("Trung Quốc · AI Agent", "提示词"),
    ("Trung Quốc · AI Agent", "topic:deepseek"),
    ("Trung Quốc · AI Agent", "topic:qwen"),
    ("Trung Quốc · Video AI", "短视频"),
    ("Trung Quốc · Video AI", "数字人"),
    ("Trung Quốc · Marketing", "抖音"),
    ("Trung Quốc · Marketing", "小红书"),
    ("Trung Quốc · Công cụ làm việc", "飞书"),
]
CHINA_QUERIES = [query for _label, query in CHINA]


def test_seed_adds_ten_china_watch_queries_after_the_sixteen() -> None:
    rows = list(WatchQuery.objects.all())[16:]

    assert [(row.label, row.query) for row in rows] == CHINA
    assert [row.position for row in rows] == list(range(17, 27))
    # Từ 20 star, mức quét Vừa (50 lượt gọi): truy vấn chữ rộng hơn truy vấn theo topic.
    assert {(row.min_stars, row.max_stars, row.budget, row.enabled) for row in rows} == {
        (20, None, 50, True)
    }


def test_seed_run_again_does_not_duplicate() -> None:
    seed_migration.seed_china_watch_queries(apps, None)

    assert WatchQuery.objects.count() == 26


def test_seed_keeps_a_query_the_owner_already_has() -> None:
    # Chủ dự án đã tự thêm "抖音" rồi tắt đi: migration không được bật lại hay tạo dòng thứ hai.
    WatchQuery.objects.filter(query__in=CHINA_QUERIES).delete()
    WatchQuery.objects.create(
        label="Của tôi", query="抖音", min_stars=100, budget=300, enabled=False, position=99
    )

    seed_migration.seed_china_watch_queries(apps, None)

    mine = WatchQuery.objects.get(query="抖音")
    assert (mine.label, mine.min_stars, mine.budget, mine.enabled) == ("Của tôi", 100, 300, False)
    assert WatchQuery.objects.filter(query__in=CHINA_QUERIES).count() == 10


def test_seed_positions_continue_after_the_largest_existing_one() -> None:
    # Chủ dự án có thể đã thêm truy vấn riêng ở cuối danh sách: truy vấn mới nối sau, không chen.
    WatchQuery.objects.filter(query__in=CHINA_QUERIES).delete()
    WatchQuery.objects.create(label="Của tôi", query="topic:llm", position=40)

    seed_migration.seed_china_watch_queries(apps, None)

    seeded = WatchQuery.objects.filter(query__in=CHINA_QUERIES)
    assert sorted(row.position for row in seeded) == list(range(41, 51))
