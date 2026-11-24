# PR B — Trending mọi cỡ (F-011) + trả nợ D-009: kế hoạch thực thi

> **Cho agent thực thi:** dùng superpowers:executing-plans. Bước dùng ô tick (`- [ ]`).

**Mục tiêu:** lượt quét hằng ngày tính và xác minh cả repo **từ 1.000 star** đang tăng mạnh (trending), không tốn thêm
lượt tìm kiếm; trước đó trả nợ D-009 (tách `features/rising/services.py` 1.670 dòng, sửa 3 điểm nhỏ).

**Kiến trúc:** dùng lại ảnh chụp star mà lượt hằng ngày đã lưu cho mọi repo trong 16 chủ đề theo dõi. Bước lọc thô
bỏ trần 1.000 star và chia 2 nhóm (`pool`): dưới 1.000 → `rising` (luật cũ), từ 1.000 → `trending` (luật mới).
Bước xác minh mới `TRENDING` (số 7) chạy sau `VERIFY`, dùng chung vòng xác minh, ngân sách riêng. Cùng bảng
`RisingCheck` (thêm cột `pool`, `is_trending`).

**Thiết kế:** `docs/designs/2026-11-23-f011-f012-kham-pha-trending.md`, mục "PR B".

## Ràng buộc chung

- Nhánh `feat/f011-trending`. Commit tiếng Việt `<loại>: <mô tả>`. TDD: test đỏ trước.
- Trending: `gain_7d ≥ 200` **và** `% tăng 7 ngày ≥ 2` (so với star 7 ngày trước; star trước ≤ 0 coi như đạt %).
  Ứng viên: ước lượng `≥ 100` và `≥ 1%`. Áp cho repo **mọi cỡ** (repo < 1.000 star tăng ≥ 200 vừa rising vừa trending).
- Ngân sách xác minh trending: `300` khi có `GITHUB_TOKEN`, `0` khi không (bỏ qua bước, ghi chú lý do).
- Số liệu chỉ từ lịch sử star chính thức (QĐ-16). Không thêm thư viện. Không đổi giao diện lớn (để PR C).
- `services.py` của rising vẫn là cửa công khai duy nhất (tính năng khác và view chỉ import `services`).
- Rising và trending **không được lẫn**: ngân sách 300 lượt của rising không được tiêu cho nhóm trending; số đếm báo
  cáo rising (`rising_count`, `unverified_count`, bảng `/rising/`) chỉ tính nhóm `rising`.

## Điểm dễ hỏng cần kiểm

1. Lẫn nhóm: `_verify` lấy dòng chưa xác minh của **cả lượt** → test chặn ở Task 4.
2. Lượt cũ đang Tạm dừng ở bước `VERIFY` khi nâng cấp → chạy tiếp phải đi sang `TRENDING`, không bỏ qua → Task 4.
3. Không token: bước trending không gọi GitHub, lượt vẫn ra báo cáo → Task 4.
4. Repo cực lớn (> 100.000 star): `star_history` trả đủ 30 ngày → `poe test-live` (Task 6).
5. Tách file làm test vá hằng số (`monkeypatch.setattr(services, "VERIFY_BUDGET_…")`) vá nhầm chỗ, test vẫn xanh
   mà không kiểm gì → Task 1 chuyển đích vá sang đúng module con.

---

### Task 1: Tách `features/rising/services.py` (D-009.1) — chỉ chuyển chỗ, không đổi hành vi

**Files:** Create `features/rising/_common.py`, `_runner.py`, `daily_run.py`, `report.py`, `overview.py`; Modify
`features/rising/services.py`, `features/rising/tests/test_verify.py`, `test_owners.py`, `test_classify_step.py`.

Chia theo nhóm việc (giữ nguyên thân hàm, chép theo khoảng dòng):
- `_common.py`: hằng số thời gian/ngân sách/câu chữ (dòng 64–144), 3 lớp lỗi, `_summary`, `_verify_budget`,
  `_owner_budget`, `_growth_facts`, `_needs_new_scan`, `_SCAN_FINISHED/_UNFINISHED`, `_RESCAN_ERROR_KINDS`,
  `_blocked_by_github`, `_busy_reason`, `_HeartbeatSleep`.
- `_runner.py`: `_DailyRunner`.
- `daily_run.py`: `live_daily_run`, `pause_stale_daily_runs`, `close_previous_days`, `prepare_daily_run`,
  `request_daily_stop`, `release_unstarted_daily_run`, `run_daily_if_due`, `execute_daily_run`,
  `classify_backlog_if_due`, `_is_live`, `_child_stop_requested`, `_ensure_nothing_live`, `_reopen_for_auto_continue`.
- `report.py`: từ "Đọc báo cáo" tới `_number` (gồm `_reported_runs`, `_paginate`, dataclass dòng báo cáo).
- `overview.py`: từ "Trạng thái hôm nay" tới hết file.
- `services.py`: docstring + `from … import X as X` cho **mọi tên công khai** của 5 module (sinh bằng script, sắp
  xếp), không còn code nghiệp vụ.

Hằng số bị test vá phải được **đọc** ở module mà test vá: `_verify_budget`/`_owner_budget` đọc
`_common.VERIFY_BUDGET_*`/`OWNER_BUDGET_*`; `_classify_repos` đọc `_common.DAILY_RUN_CLASSIFY_CALLS` → các file con
dùng `from features.rising import _common as common` và `common.X` cho 3 nhóm hằng số này.

- [ ] **Bước 1:** chạy `uv run pytest features/rising -q -p no:cacheprovider --no-cov` → ghi số test đạt (mốc trước).
- [ ] **Bước 2 (test đỏ):** sửa 6 chỗ vá: `monkeypatch.setattr(services, "VERIFY_BUDGET_WITH_TOKEN", …)` →
  `monkeypatch.setattr(_common, …)` (tương tự `VERIFY_BUDGET_ANONYMOUS`, `OWNER_BUDGET_ANONYMOUS`,
  `DAILY_RUN_CLASSIFY_CALLS`), thêm `from features.rising import _common`. Chạy → FAIL (`_common` chưa có).
- [ ] **Bước 3:** tách bằng script (chép khoảng dòng, mỗi file nhận đủ khối import gốc), rồi
  `uv run ruff check --fix --select F401,I features/rising` bỏ import thừa; gỡ dấu `DEBT(D-009)` ở đầu file.
- [ ] **Bước 4:** `uv run pytest features/rising -q …` → đúng số test như mốc; `uv run mypy` sạch; mỗi file ≤ 700 dòng.
- [ ] **Bước 5:** commit `refactor: tách services.py của rising thành module theo nhóm việc (D-009)`.

### Task 2: Ba điểm nhỏ còn lại của D-009

**Files:** `features/rising/_runner.py` (`_screen`), `features/rising/report.py` (`daily_report`),
`features/catalog/services.py`, `features/rising/_common.py`, `features/discovery/views.py`,
`features/discovery/templates/discovery/scan_detail.html`; test ở `features/rising/tests/test_verify.py`,
`test_report.py`, `features/discovery/tests/test_views.py`.

- [ ] **Bước 1 (test đỏ):**
  - `test_screen_uses_the_run_day_not_the_clock` — lượt ngày `DAY`, ảnh chụp mốc ngày `DAY-7`, chạy bước lọc thô
    lúc đồng hồ đã sang `DAY+1` 00:10 → ước lượng tính trên 7 ngày (`(stars - mốc) * 7 / 7`), không phải 8.
  - `test_new_entry_badge_follows_the_chosen_thresholds` — lượt trước có repo 1.200 star tăng 80 (không rising
    theo ngưỡng mặc định), hôm nay vẫn vậy; xem với `max_stars=2000` → repo **không** có nhãn "Mới vào danh sách".
  - `test_pruned_note_uses_the_retention_constant` (discovery) — `scan.results_pruned` thì trang hiện
    "đã dọn sau {SNAPSHOT_RETENTION_DAYS} ngày"; đổi hằng bằng monkeypatch thành 40 → trang ghi 40.
- [ ] **Bước 2:** chạy → FAIL đúng 3 test.
- [ ] **Bước 3:** `_screen` dùng `today = run.day` (lấy từ `self._check_in()`); `daily_report` lấy tập "lượt trước"
  là dòng `source=HISTORY, pool=…` (sau Task 3 có `pool`; ở task này dùng `stars__lt=max_stars, gain_7d__gte=min_gain`);
  thêm `SNAPSHOT_RETENTION_DAYS = 35` vào `features/catalog/services.py`, rising dùng hằng này (bỏ `RETENTION_DAYS`
  riêng, giữ tên cũ làm bí danh trong `_common` nếu test dùng), view `scan_detail` truyền `retention_days`.
- [ ] **Bước 4:** test rising + discovery → PASS. Gỡ mọi dấu `DEBT(D-009)` còn lại; `DEBT.md` D-009 → "Đã trả".
- [ ] **Bước 5:** commit `fix: trả nốt D-009 — lọc thô theo ngày của lượt, nhãn Mới theo ngưỡng đang lọc, số ngày dọn`.

### Task 3: Quy tắc trending + migration

**Files:** `features/rising/growth.py`, `features/rising/models.py`, migration mới `features/rising/migrations/0005_trending.py`
(sinh bằng `makemigrations rising --name trending`), `features/rising/tests/test_growth.py`.

**Interfaces — Produces:**
```python
TRENDING_MIN_GAIN_7D = 200; TRENDING_MIN_PERCENT_7D = 2.0
TRENDING_CANDIDATE_MIN_ESTIMATE_7D = 100; TRENDING_CANDIDATE_MIN_PERCENT_7D = 1.0
def is_trending(stars_now: int, gain_7d: int) -> bool
def is_trending_candidate(stars_now: int, estimate_7d: int) -> bool
RisingCheck.Pool(TextChoices): RISING = "rising"; TRENDING = "trending"
RisingCheck.pool: CharField(max_length=10, default="rising"); RisingCheck.is_trending: BooleanField(default=False)
DailyRun.trending_budget / trending_calls_used / trending_candidate_count / trending_count: PositiveIntegerField(default=0)
DailyRun.Step.TRENDING = 7, "Xác minh trending"
```
- [ ] **Bước 1 (test đỏ)** trong `test_growth.py`: `is_trending(10_200, 199) is False`, `is_trending(10_200, 200) is True`
  (200/10.000 = 2%); `is_trending(20_399, 399) is False` (399/20.000 = 1,995%), `is_trending(20_400, 400) is True`;
  `is_trending(250, 250) is True` (star trước = 0); `is_trending(800, 250) is True`;
  `is_trending_candidate(10_100, 99) is False`, `(10_100, 100) is True`, `(20_199, 199) is False` (< 1%),
  `(20_200, 200) is True`.
- [ ] **Bước 2:** chạy → FAIL. **Bước 3:** viết hàm (dùng `growth_percent_7d`), thêm trường model, `makemigrations`.
- [ ] **Bước 4:** `uv run pytest features/rising -q …` + `uv run poe migrations-check` → PASS.
- [ ] **Bước 5:** commit `feat: quy tắc trending (≥ 200 star/7 ngày và ≥ 2%) và cột dữ liệu cho F-011`.

### Task 4: Lượt hằng ngày lọc thô + xác minh trending

**Files:** `features/rising/_runner.py`, `_common.py`, `report.py`, `overview.py`, `features/rising/tests/test_trending.py` (mới),
`test_report.py`.

- `_screen`: bỏ `stars__lt`; mỗi repo: `< RISING_MAX_STARS` → luật cũ, `pool=RISING`; ngược lại →
  `is_trending_candidate`, `pool=TRENDING`. `candidate_count`/`insufficient_count` giữ nghĩa cũ (chỉ nhóm rising);
  thêm `trending_candidate_count`.
- `_verify`: `pending` lọc `pool=RISING`; xong chuyển `step=TRENDING`. Câu `VERIFY_BUDGET_NOTE` đếm nhóm rising.
- `_verify_rows(run, pending, *, budget_total: int, calls_field: str, budget_note: str)`; `_fetch_history` ghi vào
  `calls_field`. Bước mới `_verify_trending()`: chốt `trending_budget` một lần (`_trending_budget()`), budget 0 mà có
  ứng viên → ghi chú `TRENDING_SKIPPED_NOTE` ("Không có GITHUB_TOKEN — bỏ qua xác minh {count} ứng viên trending.");
  xong → `step=OWNERS`.
- `_save_history`: `is_trending=growth.is_trending(check.stars, gains.gain_7d)` cho cả hai nhóm.
- `run()`: `VERIFY → TRENDING → OWNERS`. `_classify_repos` sắp `-is_rising, -is_trending, -gain_7d`.
- `_report`: `rising_count`/`unverified_count` lọc `pool=RISING`; thêm `trending_count=checks.filter(is_trending=True)`.
- `daily_report`: chỉ lấy dòng `pool=RISING`. `latest_trending_repository_ids()` (giống `latest_rising_repository_ids`).
- `_running_headline` cho bước 7: "Đang chạy: xác minh repo trending bằng lịch sử star — đã dùng a/b lượt gọi.".
- `daily_estimate` cộng `trending_calls_used`.

- [ ] **Bước 1 (test đỏ)** `test_trending.py` (GitHub giả lập như `test_verify.py`):
  - `test_screen_puts_big_repos_in_the_trending_pool` — repo 5.000 star ước lượng +300 → dòng `pool=trending`;
    fork/archived không có dòng; repo 600 star ước lượng +40 → `pool=rising` như cũ; `candidate_count` chỉ đếm rising.
  - `test_rising_budget_is_never_spent_on_trending_rows` — ngân sách rising 1, có 1 ứng viên rising + 2 trending →
    `verify_calls_used == 1`, lượt gọi đó là của repo rising.
  - `test_trending_budget_is_separate_and_counted_per_call` — 2 ứng viên trending, ngân sách 300 →
    `trending_calls_used == 2`, cả hai `source=history`, `is_trending` đúng theo số tăng.
  - `test_trending_budget_runs_out_with_a_note` — ngân sách trending 1, 2 ứng viên → 1 xác minh, ghi chú còn 1.
  - `test_stop_during_trending_then_continue_makes_no_repeat_call`.
  - `test_trending_repo_gone_404_is_dropped`.
  - `test_no_token_skips_trending_verification_with_a_note` — không token → 0 lượt gọi trending, có ghi chú, lượt Xong
    nhưng còn sót, báo cáo vẫn lập.
  - `test_run_paused_at_verify_before_upgrade_continues_into_trending`.
  - `test_small_repo_gaining_250_is_both_rising_and_trending`.
  - trong `test_report.py`: `test_report_counts_ignore_trending_rows` — có thêm dòng trending (đã/chưa xác minh) →
    `rising_count`, `unverified_count`, `verified_count`, bảng, mục chưa xác minh **không đổi**.
- [ ] **Bước 2:** chạy → FAIL. **Bước 3:** code. **Bước 4:** `uv run pytest features/rising -q …` → PASS.
- [ ] **Bước 5:** commit `feat: lượt hằng ngày lọc và xác minh repo trending mọi cỡ, ngân sách riêng (F-011)`.

### Task 5: Giao diện tạm, lệnh `daily`, Kho repo, sổ sách

**Files:** `features/browse/forms.py`, `services.py`, `templates/browse/repos.html`, test browse;
`features/rising/templates/rising/watch.html`, `report.html` (dòng số liệu); `features/rising/management/commands/daily.py`;
`templates/base.html` không đổi; `FEATURE_MAP.md`, `docs/ARCHITECTURE.md` (QĐ-21, QĐ-22), `DEBT.md`, `TASKS.md`.

- [ ] **Bước 1 (test đỏ):** browse `test_trending_only_keeps_latest_trending_repos`,
  `test_gain_sort_shows_big_repo_gain`; rising `test_daily_command_prints_trending_counts`,
  `test_watch_history_shows_trending_count`, `test_report_stats_show_trending_count`.
- [ ] **Bước 2–4:** `BrowseFilters.trending_only` + ô "Chỉ trending (báo cáo mới nhất)" (chip như "Chỉ rising star");
  lịch sử lượt thêm cột "Trending" (`trending_count` · `trending_calls_used/trending_budget`); dòng số liệu báo cáo thêm
  "N trending"; lệnh `daily` in "xác minh trending a/b" và "Trending: N". Test → PASS.
- [ ] **Bước 5:** sổ sách: FEATURE_MAP (F-011 mới; F-005 bước 7, cột `pool`; F-010 `trending_only`), ARCHITECTURE
  QĐ-21 (tách module, `services.py` là cửa duy nhất) và QĐ-22 (trending, sửa QĐ-16), CLAUDE.md mục 3 dòng "Service
  lớn", TASKS.md. `uv run poe check` → xanh. Commit `docs: F-011 trending — QĐ-21, QĐ-22, bản đồ tính năng`.

### Task 6: Kiểm chứng và mở PR

- [ ] `uv run poe check` xanh (mã thoát 0), ghi số test và độ phủ.
- [ ] `uv run poe test-live` (cần token) — thêm `test_live_star_history_of_a_very_big_repo` (repo > 100.000 star theo
  `github_id`): đủ 30 ngày, `gain_30d > 0`.
- [ ] Chạy thật trên **bản sao** CSDL: chép `data/oss_radar.sqlite3` → `data/f011-copy.sqlite3`; cấu hình nháp
  (`config.settings` + đổi tên CSDL, `SCHEDULED_JOBS = []`) để `.env` thật vẫn được đọc mà không chép `.env`;
  `migrate` rồi `daily`. Ghi vào PR: số ứng viên trending, đã xác minh, lượt gọi/ngân sách, số phút, top 10 trending
  (đối chiếu tay 3 repo trên GitHub), số rising so với lượt 27/10.
- [ ] Trình duyệt (máy chủ xem thử trên bản sao, không bật lịch): `/repos/?trending_only=on&sort=gain`, lịch sử lượt ở
  `/rising/watch/`, dòng số liệu ở `/rising/`.
- [ ] Rà soát độc lập cả nhánh; sửa lỗi quan trọng theo TDD; mở PR (làm gì, được gì, kiểm thế nào, phần chưa kiểm).
