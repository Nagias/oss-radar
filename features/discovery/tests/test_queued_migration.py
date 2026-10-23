"""Nợ D-008: dòng cũ thời F-001 còn trạng thái "queued" (không còn trong danh sách trạng thái)."""

import importlib

import pytest
from django.apps import apps

from features.discovery.models import ScanRun

pytestmark = pytest.mark.django_db

_MIGRATION = importlib.import_module("features.discovery.migrations.0005_close_queued_scans")


def test_old_queued_scans_become_failed_with_reason() -> None:
    old = ScanRun.objects.create(query="topic:ai-agent", status="queued")
    untouched = ScanRun.objects.create(query="topic:llm", status=ScanRun.Status.SUCCEEDED)

    _MIGRATION.close_queued_scans(apps, None)
    old.refresh_from_db()
    untouched.refresh_from_db()

    assert old.status == ScanRun.Status.FAILED
    assert "F-001" in old.error_message
    assert old.get_status_display() == "Lỗi"
    assert untouched.status == ScanRun.Status.SUCCEEDED


def test_migration_is_safe_to_run_twice() -> None:
    ScanRun.objects.create(query="topic:ai-agent", status="queued")

    _MIGRATION.close_queued_scans(apps, None)
    _MIGRATION.close_queued_scans(apps, None)

    assert ScanRun.objects.filter(status="queued").count() == 0
