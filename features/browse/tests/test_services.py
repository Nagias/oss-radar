"""Duyệt kho: lọc theo nhãn (HOẶC trong lớp, VÀ giữa hai lớp), số liệu, sắp, trang, ẩn Nghi cao."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.utils import timezone

from features.browse import services
from features.browse.services import BrowseFilters
from features.browse.tests.conftest import add_repo, label
from features.discovery.models import ScanResult, ScanRun
from features.rising.models import DailyRun, RisingCheck
from features.scoring import services as scoring

pytestmark = pytest.mark.django_db

DEFAULT = BrowseFilters()


def names(filters: BrowseFilters = DEFAULT) -> list[str]:
    return [row.repository.full_name for row in services.browse(filters).rows]


def test_default_lists_everything_by_stars() -> None:
    add_repo(1, stars=50)
    add_repo(2, stars=500)
    add_repo(3, stars=200)

    page = services.browse(DEFAULT)

    assert [row.repository.github_id for row in page.rows] == [2, 3, 1]
    assert (page.total, page.page, page.pages) == (3, 1, 1)


def test_labels_or_within_axis_and_between_axes() -> None:
    video_creator = add_repo(1)
    label(video_creator, audience=("creator",), aspects=("video",))
    video_marketer = add_repo(2)
    label(video_marketer, audience=("marketer",), aspects=("video", "ads"))
    image_creator = add_repo(3)
    label(image_creator, audience=("creator",), aspects=("image",))
    add_repo(4)  # chưa phân loại

    either_audience = replace(DEFAULT, audience=("creator", "marketer"))
    both_axes = replace(DEFAULT, audience=("creator", "marketer"), aspects=("video",))

    assert sorted(names(either_audience)) == ["chu/repo-1", "chu/repo-2", "chu/repo-3"]
    assert sorted(names(both_axes)) == ["chu/repo-1", "chu/repo-2"]
    assert names(replace(DEFAULT, unclassified=True)) == ["chu/repo-4"]


def test_rows_carry_labels_scores_and_gain() -> None:
    repo = add_repo(1)
    label(repo, audience=("creator",), aspects=("video",))
    run = DailyRun.objects.create(day=timezone.localdate(), status="succeeded", step=4)
    RisingCheck.objects.create(
        daily_run=run, repository=repo, stars=100, source="history", gain_7d=77, is_rising=True
    )

    [row] = services.browse(DEFAULT).rows

    assert row.labels is not None
    assert [c.code for c in row.labels.aspects] == ["video"]
    assert row.labels.reason == "lý do 1"
    assert row.scores.quality.total > 0
    assert row.gain_7d == 77


def test_number_and_text_filters() -> None:
    add_repo(1, stars=50, language="Go", description="Công cụ crawl web")
    add_repo(2, stars=500, language="Python", created_at=timezone.now() - timedelta(days=5))
    add_repo(3, stars=5000, language="python", license_spdx="AGPL-3.0", full_name="ai/Crawler")

    assert names(replace(DEFAULT, q="crawl")) == ["ai/Crawler", "chu/repo-1"]
    assert names(replace(DEFAULT, language="Python")) == ["ai/Crawler", "chu/repo-2"]
    assert names(replace(DEFAULT, min_stars=100, max_stars=1000)) == ["chu/repo-2"]
    assert names(replace(DEFAULT, created_days=30)) == ["chu/repo-2"]
    assert names(replace(DEFAULT, commercial=True)) == ["chu/repo-2", "chu/repo-1"]


def test_rising_only_uses_latest_report() -> None:
    old_star, new_star = add_repo(1), add_repo(2)
    add_repo(3)
    older = DailyRun.objects.create(
        day=timezone.localdate() - timedelta(days=1), status="succeeded", step=4
    )
    newest = DailyRun.objects.create(day=timezone.localdate(), status="succeeded", step=4)
    for run, repo in ((older, old_star), (newest, new_star)):
        RisingCheck.objects.create(
            daily_run=run, repository=repo, stars=100, source="history", gain_7d=90, is_rising=True
        )

    assert names(replace(DEFAULT, rising_only=True)) == ["chu/repo-2"]


def test_rising_only_without_any_report_is_empty() -> None:
    add_repo(1)

    assert names(replace(DEFAULT, rising_only=True)) == []


def test_scan_filter_lists_every_repo_of_that_scan() -> None:
    first, second = add_repo(1), add_repo(2)
    add_repo(3)
    scan = ScanRun.objects.create(query="topic:x", status=ScanRun.Status.SUCCEEDED)
    for repo in (first, second):
        ScanResult.objects.create(scan_run=scan, repository=repo, is_new=True)

    assert names(replace(DEFAULT, scan=scan.pk)) == ["chu/repo-1", "chu/repo-2"]


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("stars", [3, 2, 1]),
        ("forks", [1, 2, 3]),
        ("created", [2, 1, 3]),
        ("pushed", [1, 3, 2]),
        ("gain", [2, 1, 3]),  # repo 3 chưa từng được xét: xếp cuối
    ],
)
def test_sorting(sort: str, expected: list[int]) -> None:
    now = timezone.now()
    one = add_repo(1, stars=10, forks=900, created_at=now - timedelta(days=50), pushed_at=now)
    two = add_repo(2, stars=20, forks=50, created_at=now - timedelta(days=5), pushed_at=None)
    add_repo(
        3,
        stars=30,
        forks=1,
        created_at=now - timedelta(days=500),
        pushed_at=now - timedelta(days=9),
    )
    run = DailyRun.objects.create(day=timezone.localdate(), status="succeeded", step=4)
    RisingCheck.objects.create(daily_run=run, repository=one, stars=10, source="history", gain_7d=5)
    RisingCheck.objects.create(
        daily_run=run, repository=two, stars=20, source="history", gain_7d=50
    )

    rows = services.browse(replace(DEFAULT, sort=sort)).rows

    assert [row.repository.github_id for row in rows] == expected


def test_sort_by_quality_uses_stored_scores_unscored_last() -> None:
    add_repo(1, stars=20, forks=0, license_spdx="")
    add_repo(2, stars=50_000, forks=9000, owner_type="Organization")
    scoring.refresh_scores()
    add_repo(3, stars=900_000)  # mới vào kho, chưa có điểm lưu sẵn

    assert names(replace(DEFAULT, sort="quality")) == ["chu/repo-2", "chu/repo-1", "chu/repo-3"]


def test_high_suspicion_hidden_by_default_unless_asked() -> None:
    created = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)
    add_repo(1, stars=613, forks=2, created_at=created, pushed_at=created)  # Nghi cao (65)
    add_repo(2, stars=1000, forks=100)
    scoring.refresh_scores()
    add_repo(3, stars=613, forks=2, created_at=created, pushed_at=created)  # chưa có điểm: không ẩn

    assert names() == ["chu/repo-2", "chu/repo-3"]
    assert names(replace(DEFAULT, show_suspicious=True)) == [
        "chu/repo-2",
        "chu/repo-1",
        "chu/repo-3",
    ]


def test_pagination_50_per_page_and_page_clamped() -> None:
    for github_id in range(1, 53):
        add_repo(github_id, stars=1000 - github_id)

    first = services.browse(DEFAULT)
    second = services.browse(replace(DEFAULT, page=2))
    beyond = services.browse(replace(DEFAULT, page=99))

    assert (first.total, first.pages, len(first.rows)) == (52, 2, 50)
    assert [row.repository.github_id for row in second.rows] == [51, 52]
    assert beyond.page == 2


def test_counts_per_label_and_languages() -> None:
    a, b = add_repo(1, language="Go"), add_repo(2, language="Go")
    add_repo(3, language="Rust")
    label(a, audience=("creator",), aspects=("video",))
    label(b, audience=("creator",), aspects=("image",))

    page = services.browse(DEFAULT)

    assert page.counts["creator"] == 2
    assert page.counts["video"] == 1
    assert page.counts[services.UNCLASSIFIED] == 1
    assert page.languages == ["Go", "Rust"]


def test_query_count_does_not_grow_with_rows(django_assert_max_num_queries: Any) -> None:
    for github_id in range(1, 6):
        label(add_repo(github_id), audience=("creator",), aspects=("video",))
    with django_assert_max_num_queries(12) as few:
        services.browse(DEFAULT)
    for github_id in range(6, 51):
        label(add_repo(github_id), audience=("creator",), aspects=("video",))

    with django_assert_max_num_queries(len(few.captured_queries)):
        services.browse(DEFAULT)
