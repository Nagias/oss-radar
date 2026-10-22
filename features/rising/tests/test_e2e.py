"""Kiểm chứng tự động cho F-005 — đi đúng đường chủ dự án đi: lệnh `daily` rồi mở trang Rising star.

Quét lại 2 truy vấn theo dõi (300 repo) → lọc thô bằng ảnh chụp 3 ngày trước → xác minh bằng lịch sử
star → trang `/rising/` có đúng 5 rising star, đúng thứ tự, biểu đồ 30 điểm. Chỉ GitHub là giả lập;
mọi lớp còn lại chạy thật, kể cả CSDL và template.
"""

import re
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pytest_django.fixtures import Settings

from features.catalog.models import Repository, StarSnapshot
from features.catalog.services import upsert_repositories
from features.rising.growth import SERIES_DAYS
from features.rising.models import DailyRun, RisingCheck, WatchQuery
from features.rising.tests.conftest import FROM, TO, UseFake, history
from tests.factories import make_github_repo
from tests.fakes import make_search_items

pytestmark = pytest.mark.django_db

# id repo → (star tăng so với ảnh chụp 3 ngày trước, star tăng 7 ngày theo lịch sử chính thức).
# Thứ tự theo lịch sử: 11, 22, 33, 44, 55; theo ước lượng từ ảnh chụp thì khác (lại có kẻ lừa 66)
# → trang chỉ đúng khi xếp theo số đã xác minh.
RISERS = {11: (30, 210), 22: (90, 182), 33: (45, 119), 44: (60, 77), 55: (30, 56)}
DECOY = 66  # ước lượng từ ảnh chụp rất cao (280) nhưng lịch sử chỉ tăng 35 trong 7 ngày
REPOS = 300
WITH_SNAPSHOT = (
    120  # repo 1..120 có ảnh chụp cũ; 121..300 là repo cũ chưa có mốc → "chưa đủ dữ liệu"
)


@pytest.fixture
def use_fake(use_fake_github: UseFake) -> UseFake:
    return use_fake_github


def test_daily_e2e_rescan_verify_report(
    client: Client,
    watch_list: list[WatchQuery],
    use_fake: UseFake,
    settings: Settings,
) -> None:
    settings.GITHUB_TOKEN = "test-token"
    WatchQuery.objects.filter(pk=watch_list[2].pk).delete()  # hai truy vấn theo dõi
    items = make_search_items(REPOS, start=FROM, end=TO, stars=lambda i: 300 + i)
    stars_now = {entry["id"]: entry["stargazers_count"] for entry in items}
    gain_3d = {repo_id: snapshot_gain for repo_id, (snapshot_gain, _) in RISERS.items()}
    gain_3d[DECOY] = 120
    upsert_repositories(
        [
            make_github_repo(
                github_id=repo_id,
                full_name=f"gia-lap/repo-{repo_id}",
                stars=stars_now[repo_id] - gain_3d.get(repo_id, 2),
            )
            for repo_id in range(1, WITH_SNAPSHOT + 1)
        ],
        seen_at=timezone.now() - timedelta(days=3),
    )
    histories = {
        repo_id: history(dict.fromkeys(range(SERIES_DAYS), history_gain // 7))  # đều mỗi ngày
        for repo_id, (_, history_gain) in RISERS.items()
    }
    histories[55] = history({0: 50, 1: 6})  # dồn một ngày → cờ cảnh giác
    histories[DECOY] = history(dict.fromkeys(range(SERIES_DAYS), 5))
    fake = use_fake(items, histories)

    out = StringIO()
    call_command("daily", stdout=out)

    run = DailyRun.objects.get()
    assert run.status == DailyRun.Status.SUCCEEDED
    assert run.scans.count() == 2
    assert run.new_repo_count == REPOS - WITH_SNAPSHOT  # 120 repo đã có từ ảnh chụp mốc
    assert (run.candidate_count, run.rising_count) == (6, 5)
    assert run.insufficient_count == REPOS - WITH_SNAPSHOT
    assert sorted(fake.history.requested) == sorted([*RISERS, DECOY])  # chỉ xác minh ứng viên
    assert run.verify_calls_used == 6
    assert Repository.objects.count() == REPOS
    assert StarSnapshot.objects.filter(day=timezone.localdate()).count() == REPOS
    assert "Rising star: 5" in out.getvalue()

    response = client.get(reverse("rising:report"))

    page = response.text
    assert response.status_code == 200
    assert "Xong lúc" in page
    assert "5 rising star" in page
    names = re.findall(r"<strong>gia-lap/(repo-\d+)</strong>", page)
    assert names == ["repo-11", "repo-22", "repo-33", "repo-44", "repo-55"]
    assert "repo-66" not in page  # kẻ lừa: ước lượng cao, xác minh thấp → không vào bảng
    polylines = re.findall(r'<polyline points="([^"]+)"', page)
    assert len(polylines) == 5
    assert {len(points.split()) for points in polylines} == {SERIES_DAYS}
    assert page.count("Mới vào danh sách") == 5
    assert "Dồn một ngày" in page  # cờ của repo-55
    assert "+210 star trong 7 ngày" in page
    for scan_id in run.scans.values_list("scan_run_id", flat=True):
        assert reverse("discovery:scan_detail", args=[scan_id]) in page

    # Không chạy lại một ngày đã xong; trang không còn nút Chạy ngay.
    with pytest.raises(CommandError, match="Hôm nay đã quét xong"):
        call_command("daily", stdout=StringIO())
    assert "Chạy ngay" not in page

    # Bộ lọc: nâng ngưỡng tăng lên 100 → chỉ còn 3 repo đầu.
    filtered = client.get(reverse("rising:report"), {"min_gain": "100"}).text
    assert re.findall(r"<strong>gia-lap/(repo-\d+)</strong>", filtered) == [
        "repo-11",
        "repo-22",
        "repo-33",
    ]
    assert RisingCheck.objects.filter(is_rising=True).count() == 5
