"""Migration dữ liệu: mỗi repo đang có trong kho được tạo sẵn một ảnh chụp star đầu tiên."""

import importlib
from datetime import UTC, date, datetime

import pytest
from django.apps import apps

from features.catalog.models import Repository, StarSnapshot
from features.catalog.services import upsert_repositories
from tests.factories import make_github_repo

pytestmark = pytest.mark.django_db

seed_migration = importlib.import_module("features.catalog.migrations.0003_seed_star_snapshots")


def test_seed_creates_one_snapshot_per_repository_from_last_seen() -> None:
    upsert_repositories(
        [make_github_repo(github_id=1, full_name="a/one", stars=10)],
        seen_at=datetime(2026, 10, 18, 8, 0, tzinfo=UTC),
    )
    # 20:00 UTC ngày 19 = 03:00 ngày 20 giờ Việt Nam: ngày của ảnh chụp phải tính theo giờ Việt Nam.
    upsert_repositories(
        [make_github_repo(github_id=2, full_name="b/two", stars=20)],
        seen_at=datetime(2026, 10, 19, 20, 0, tzinfo=UTC),
    )
    StarSnapshot.objects.all().delete()  # quay về trạng thái trước khi có bảng ảnh chụp

    seed_migration.seed_snapshots(apps, None)

    rows = StarSnapshot.objects.order_by("repository__github_id")
    assert [(r.repository.github_id, r.day, r.stars) for r in rows] == [
        (1, date(2026, 10, 18), 10),
        (2, date(2026, 10, 20), 20),
    ]
    assert {r.repository_id: r.captured_at for r in rows} == {
        repo.pk: repo.last_seen_at for repo in Repository.objects.all()
    }


def test_seed_is_safe_to_run_twice() -> None:
    upsert_repositories([make_github_repo(github_id=1)], seen_at=datetime(2026, 10, 18, tzinfo=UTC))
    StarSnapshot.objects.all().delete()

    seed_migration.seed_snapshots(apps, None)
    seed_migration.seed_snapshots(apps, None)

    assert StarSnapshot.objects.count() == 1
