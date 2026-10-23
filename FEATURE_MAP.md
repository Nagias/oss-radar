# FEATURE_MAP — bản đồ tính năng

Bản đồ để người và agent tìm đúng chỗ trong 30 giây: tính năng nào, nằm ở thư mục nào, vào bằng đường nào,
test ở đâu, đang nợ gì.

**Luật cập nhật**
- Thêm/sửa/xoá tính năng → cập nhật file này **trong cùng PR**. PR thiếu cập nhật thì không merge.
- Mỗi thư mục `features/<tên>/` và `integrations/<tên>/` phải có mặt trong file này (dạng `` `features/<tên>/` ``).
  `tests/test_guards.py` kiểm tự động — quên là CI đỏ.
- Mã tính năng `F-NNN` tăng dần, không dùng lại.

## Tổng quan

| Mã | Tính năng | Trạng thái | Thư mục | Lối vào | Test chính | Nợ |
|---|---|---|---|---|---|---|
| F-001 | Quét GitHub theo truy vấn → lưu không trùng → xem sắp theo star | Đã gộp vào F-002 (= mức Nhanh) | `features/discovery/` | như F-002 | `features/discovery/tests/` | — |
| F-002 | Quét sâu: chia lát vượt trần 1.000 kết quả, chạy nền, ngân sách, giãn nhịp, dừng/tiếp tục, độ phủ | Chạy thật | `features/discovery/` | Web `/`, `/scans/<id>/`, nút Dừng/Tiếp tục; lệnh `manage.py scan` | `features/discovery/tests/test_deep_scan.py`, `test_e2e.py`, `test_auto_resume.py` | D-007 |
| F-005 | Rising star + lượt quét hằng ngày: ảnh chụp star, lọc thô, xác minh bằng lịch sử star chính thức, lịch chạy trong app, chạy bù, tự chạy tiếp | Chạy thật | `features/rising/` | Web `/rising/`, `/rising/watch/`, nút Chạy ngay/Chạy tiếp/Dừng; lệnh `manage.py daily`; tự chạy sau 7:00 khi app mở | `features/rising/tests/test_daily_run.py`, `test_verify.py`, `test_e2e.py` | D-009 |
| F-006 | Chấm điểm Chất lượng / Tiềm năng có giải thích, lọc star giả (ẩn "Nghi cao", có nút hiện), hồ sơ chủ repo cho rising star | Chạy thật | `features/scoring/` | Cột điểm ở `/rising/` và `/scans/<id>/`; bước "Lấy hồ sơ chủ repo" của lượt hằng ngày | `features/scoring/tests/`, `features/rising/tests/test_owners.py` | — |

## Mô-đun lõi và cửa ra ngoài

| Mô-đun | Vai trò | Ai được dùng | Test |
|---|---|---|---|
| `features/catalog/` | Lõi "kho repo": bảng `Repository` (khoá chống trùng `github_id`; có `open_issues` từ F-006), hàm `upsert_repositories` (ghi kèm ảnh chụp star `StarSnapshot` theo ngày); `baseline_snapshots`, `prune_snapshots`; hồ sơ chủ repo `OwnerProfile` (`save_owner_profile`, `mark_owner_missing`, `owner_profiles_for`, `logins_needing_profile`). Nơi DUY NHẤT ghi ba bảng này | Mọi tính năng, qua `features.catalog.services` | `features/catalog/tests/` |
| `integrations/github/` | Cửa ra GitHub REST API: `GitHubClient.search_repositories`, `GitHubClient.star_history` (lịch sử star theo `github_id`), `GitHubClient.get_user` (hồ sơ tài khoản), dataclass `GitHubRepo`/`RepoSearchPage`/`StarHistory`/`GitHubUser`, lỗi có tên (`GitHubRateLimitError`, `GitHubAuthError`…); `pacing.py`: giãn nhịp, chờ hồi lượt, gọi lại khi lỗi tạm thời, `CallBudget` | Service của các tính năng, qua `get_github_client(sleep=, budget=)` | `integrations/github/tests/` |
| `core/` | Hạ tầng dùng chung, không phải tính năng: `core.background` chạy việc nền trên MỘT luồng trong tiến trình web (`submit`, `submit_if_idle`, `busy_label`, `relabel` — QĐ-14); `core.scheduler` bộ nhịp gọi `settings.SCHEDULED_JOBS` (QĐ-15); lệnh `runserver` của dự án bật bộ nhịp. Chỉ hai file này được tạo luồng | View và lệnh của các tính năng | `core/tests/` |

## Chi tiết từng tính năng

### F-006 — Chấm điểm Chất lượng / Tiềm năng, lọc star giả
- **Phục vụ vế nào của mục tiêu:** không rác (lọc star giả), tìm đúng (xếp theo chất lượng/tiềm năng thay vì
  chỉ theo star); nguyên tắc 6 — mọi điểm mở ra xem được từng thành phần.
- **Người dùng làm gì → thấy gì:** mở `/rising/` → bảng rising star có 3 cột **Tiềm năng**, **Chất lượng**,
  **Nghi star giả**; bấm vào điểm thì thấy từng thành phần ("Phổ biến 20/30 — 1.000 star"…). Mặc định sắp
  theo Tiềm năng, ô **Sắp theo** đổi về "Tăng 7 ngày". Repo "Nghi cao" (≥ 60) không nằm ở bảng chính: dòng
  **"Đã ẩn N repo nghi star giả — Hiện"** mở ra danh sách kèm lý do; repo "Cần xem" (30–59) có nhãn vàng.
  Đầu trang: "47 rising star (đã ẩn 2 nghi star giả)". Mục chưa xác minh có Tiềm năng "(ước lượng)". Trang
  `/scans/<id>/` có cột Chất lượng và Nghi star giả, cũng ẩn "Nghi cao" (không có Tiềm năng).
- **Luồng chạy:** trang gọi `rising.services.daily_report` / `discovery.services.scored_results` →
  `scoring.services.score_repositories` (đọc `OwnerProfile` một lần cho cả lô) → `scoring.rules`
  (`quality_score`, `potential_score`, `suspicion_score`). Lượt hằng ngày thêm bước 4 "Lấy hồ sơ chủ repo"
  (`DailyRun.Step.OWNERS`, số 5): chủ của rising star chưa có hồ sơ hoặc hồ sơ quá 30 ngày (repo đang bị
  nghi từ 30 điểm lấy trước — chỉ ở đó hồ sơ chủ đổi được kết luận) →
  `scoring.services.fetch_owner_profiles` → `GitHubClient.get_user` → `catalog.services.save_owner_profile`.
- **Thành phần:**
  - hàm thuần: `features/scoring/rules.py` (hằng số trọng số, ngưỡng "Cần xem" 30 / "Nghi cao" 60)
  - service: `score_repositories`, `repo_facts`, `owners_to_fetch`, `fetch_owner_profiles`
  - template con: `scoring/_score.html`, `scoring/_suspicion.html` (dùng ở `rising/report.html`,
    `discovery/scan_detail.html`)
  - model (ở `catalog`): `OwnerProfile`, trường `Repository.open_issues`; (ở `rising`): `DailyRun.owner_budget`,
    `owner_calls_used`, bước `OWNERS`
  - form: ô `sort` của `ReportFilterForm`
- **Phụ thuộc:** `catalog.services` (hồ sơ chủ, repo), `integrations.github` (`get_user`). `rising` và
  `discovery` gọi vào `scoring`; `scoring` không gọi ngược lại.
- **Kiểm chứng tự động:** `features/scoring/tests/test_rules.py` (mọi mốc biên, 3 ví dụ thật của thiết kế),
  `test_services.py` (hồ sơ chủ, GitHub giả, template con); `features/rising/tests/test_owners.py` (bước hồ
  sơ chủ: mỗi chủ một lần, hết ngân sách, sập rồi chạy tiếp không gọi lại, 404, chặn, token sai, Dừng);
  `test_report.py`, `test_views.py` (sắp, ẩn sau bộ lọc); `features/discovery/tests/test_views.py`. Gọi
  GitHub thật: `uv run poe test-live` (thêm 1 lượt `get_user`).
- **Kiểm chứng tay:** `uv run poe dev`, mở `http://127.0.0.1:8765/rising/`, bấm vào điểm, bấm "Hiện" ở dòng
  đã ẩn; mở một lần quét bất kỳ.
- **Nợ liên quan:** không có nợ mới. D-007 (trang lần quét 500 repo) vẫn giữ; D-009 xem sổ nợ.

### F-005 — Rising star + lượt quét hằng ngày
- **Phục vụ vế nào của mục tiêu:** tiềm năng (repo dưới 1.000 star tăng nhanh), tìm đủ (mỗi ngày quét lại
  danh sách theo dõi nên repo mới không bị lỡ), không rác (cờ cảnh giác: dồn một ngày, repo rất mới, không
  mô tả).
- **Người dùng làm gì → thấy gì:** mở app sau 7:00 → lượt hằng ngày tự chạy (hoặc bấm **Chạy ngay**) →
  trang `/rising/` hiện tiến độ ("đã xong k/16 truy vấn"), xong thì hiện bảng rising star: +1/+7/+30 ngày,
  tăng %, tuổi repo, biểu đồ 30 ngày, nhãn **Mới vào danh sách**, cờ cảnh giác, dòng "Vì sao có mặt" ghi
  nguồn và khoảng ngày UTC; mục "Ứng viên chưa xác minh" (ước lượng, ghi rõ) và "Chưa đủ dữ liệu". Lọc
  nhanh theo star tối đa và mức tăng tối thiểu. Trang `/rising/watch/`: thêm/sửa/tắt truy vấn theo dõi,
  ước lượng lượt gọi và thời gian mỗi ngày, lịch sử các lượt, nút **Chạy ngay / Chạy tiếp / Dừng**. Trong
  lúc lượt chạy, nút Quét ở trang chủ bị khoá kèm nhãn việc đang chạy.
- **Luồng chạy:** `core.scheduler` (bật trong `runserver`) cứ 5 phút → `rising.services.run_daily_if_due`
  (đóng lượt hôm trước còn dở, tự chạy tiếp lượt bị gián đoạn ≤ 3 lần, sau 7:00 chưa có lượt thì tạo) →
  `execute_daily_run`: bước 1 quét lại từng `WatchQuery` bằng `discovery.services.start_scan/execute_scan`
  (nguồn "hằng ngày") → bước 2 lọc thô bằng `catalog.services.baseline_snapshots` + `growth.estimate_gain_7d`
  → bước 3 xác minh bằng `GitHubClient.star_history` (ngân sách 300 lượt có token / 50 không token) →
  bước 4 lấy hồ sơ chủ repo của rising star (F-006) → bước 5 đếm, dọn ảnh chụp và kết quả quét hằng
  ngày cũ hơn 35 ngày.
- **Thành phần:**
  - model: `WatchQuery` (16 truy vấn gợi ý tạo sẵn), `DailyRun` (bước, trạng thái, nhịp sống, ngân sách,
    số đếm, `problems`), `DailyRunScan` (truy vấn ↔ lần quét), `RisingCheck` (số tăng, chuỗi 30 ngày, nguồn,
    cờ)
  - hàm thuần: `features/rising/growth.py` (tính +1/+7/+30 ngày theo ngày UTC, ước lượng, quy tắc rising,
    cờ, điểm biểu đồ)
  - service: `run_daily_if_due`, `prepare_daily_run`, `execute_daily_run`, `request_daily_stop`,
    `release_unstarted_daily_run`, `live_daily_run`, `close_previous_days`, `pause_stale_daily_runs`,
    `daily_report`, `latest_report_run`, `report_run_for`, `report_days`, `today_status`, `watch_overview`,
    `daily_estimate`, `recent_daily_runs`
  - form: `WatchQueryForm`, `ReportFilterForm`
  - view/URL (`app_name = "rising"`): `report` (`/rising/`), `watch` (`/rising/watch/`), `watch_edit`
    (`/rising/watch/<id>/`), `run_now` (POST `/rising/run/`), `stop` (POST `/rising/runs/<id>/stop/`)
  - template: `rising/report.html`, `watch.html`, `watch_edit.html`, `_today.html`, `_watch_form.html`
  - lệnh: `manage.py daily` (chạy lượt của hôm nay ở tiền cảnh)
- **Phụ thuộc:** `discovery.services` (quét, tự chạy tiếp, dọn kết quả), `catalog.services` (ảnh chụp
  star), `integrations.github` (`star_history`), `core.background`, `core.scheduler`.
- **Kiểm chứng tự động:** `features/rising/tests/` — hàm thuần với phản hồi lịch sử star thật đã lưu; lượt
  hằng ngày với GitHub giả lập (quét lại, lọc thô, xác minh, hết ngân sách, repo bị xoá 404, bị gián đoạn
  rồi chạy tiếp, Dừng, sang ngày mới, lỗi token rồi Chạy tiếp); lịch (trước/sau 7:00, chạy bù, tối đa 3
  lần tự chạy tiếp); trang và lệnh; `test_e2e.py` chạy `manage.py daily` trên 300 repo giả rồi mở `/rising/`.
  `features/discovery/tests/test_auto_resume.py` cho phần trả D-006. Gọi GitHub thật: `uv run poe test-live`.
- **Kiểm chứng tay:** `uv run poe dev`, mở `http://127.0.0.1:8765/rising/` sau 7:00 (lượt tự chạy) hoặc
  bấm Chạy ngay; sửa một file `.py` giữa lúc chạy để server khởi động lại → khoảng 5 phút sau lượt tự nối.
- **Nợ liên quan:** D-009 (4 điểm để sau).

### F-002 — Quét sâu (TÍNH NĂNG MẪU: tính năng mới copy cấu trúc `features/discovery/`)
- **Phục vụ vế nào của mục tiêu:** tìm đủ (vượt trần 1.000 kết quả), không trùng, không rác (ngưỡng star).
- **Người dùng làm gì → thấy gì:** mở `http://127.0.0.1:8765` → gõ truy vấn (vd `topic:ai-video`), chọn star
  tối thiểu (mặc định 10) / tối đa, khoảng ngày tạo, mức quét (Nhanh 1 · Vừa 50 · Sâu 300 · Hết cỡ 1.000
  lượt gọi) → bấm **Quét** → sang ngay trang tiến độ (tự cập nhật 3 giây): đã lấy / GitHub báo, **độ phủ**,
  lượt gọi, lát đã xử lý, "đang chờ GitHub tới …", nút **Dừng**. Xong: bảng repo sắp theo star (hiện 500
  repo đầu), nhãn Mới/Đã có, "Chỗ còn sót" (lát bị cắt, chưa chắc đủ, lỗi), form **Tiếp tục** + thêm ngân sách.
  Mỗi lúc chỉ một lần quét (nút Quét bị khoá khi đang có lần khác chạy).
- **Luồng chạy:** `views.home` (POST) → `ScanForm.to_request()` → `services.start_scan` (giữ chỗ "đang chạy"
  + lát gốc, kiểm "có lần khác đang chạy" trong transaction) → `core.background.submit(services.execute_scan)`
  → vòng lặp: lát `pending` có `stack_order` lớn nhất → `slicing.build_query` → `get_github_client(sleep=
  HeartbeatSleeper, budget=CallBudget)` → trang 1: > 1.000 thì `slicing.split` thành 2 lát con (mới/star cao
  trước), ≤ 1.000 thì lấy đủ trang → `catalog.services.upsert_repositories` + `ScanResult` → lặp tới hết lát,
  hết ngân sách, bấm Dừng, hoặc lỗi.
- **Thành phần:**
  - model: `ScanRun` (phạm vi, ngân sách, lượt gọi, nhịp sống, trạng thái, lý do), `ScanSlice` (từng lát và
    điểm dừng), `ScanResult` (repo nào trong lần quét nào, `is_new`)
  - logic chia lát (hàm thuần): `features/discovery/slicing.py`
  - service: `start_scan`, `execute_scan`, `resume_scan`, `request_stop`, `live_scan`, `pause_stale_scans`,
    `recent_scans`, `scan_results`, `problem_slices`, `slice_progress`, `HeartbeatSleeper`
  - form: `ScanForm`, `ResumeForm` — dùng chung cho web và lệnh
  - view/URL: `home` (`/`), `scan_detail` (`/scans/<id>/`), `scan_stop` (POST `/scans/<id>/stop/`),
    `scan_resume` (POST `/scans/<id>/resume/`) — `app_name = "discovery"`
  - template: `discovery/home.html`, `discovery/scan_detail.html`
  - lệnh: `manage.py scan "<q>" [--min-stars N] [--max-stars N] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
    [--budget 1|50|300|1000]`; `manage.py scan --resume ID [--extra-budget N]`
- **Phụ thuộc:** `features.catalog.services.upsert_repositories`; `integrations.github` (client, pacing);
  `core.background.submit`.
- **Kiểm chứng tự động:** `features/discovery/tests/` — chia lát, vòng quét sâu với GitHub giả lập hiểu truy
  vấn (`tests/fakes.py`, dựng từ khuôn phản hồi thật), dừng/tiếp tục, form, view, lệnh; `test_e2e.py` bấm
  Quét mức Sâu trên 1.500 repo → độ phủ 100%, quét lại không trùng. Gọi GitHub thật: `uv run poe test-live`.
- **Kiểm chứng tay:** `uv run python manage.py scan "topic:ai-video" --budget 300`; hoặc mở trình duyệt,
  quét mức Vừa, bấm Dừng rồi Tiếp tục.
- **Nợ liên quan:** D-007 (trang chỉ hiện 500 repo đầu). D-008 đã trả (2026-10-23). D-006 đã trả ở F-005
  (lần quét bị gián đoạn tự chạy tiếp).

### F-001 — Quét GitHub theo truy vấn (bộ khung đi được)
- Đã gộp vào F-002 (2026-10-22, chủ dự án chốt): "quét nhanh" = mức **Nhanh** (1 lượt gọi) của quét sâu.

<!-- Khuôn cho mỗi tính năng — copy khối dưới, điền đủ các mục:

### F-NNN — <Tên tính năng>
- **Phục vụ vế nào của mục tiêu:** tìm đúng / tìm đủ / không trùng / không rác
- **Người dùng làm gì → thấy gì:** …
- **Luồng chạy:** lối vào → service → (integrations) → model → giao diện
- **Thành phần:** model …; service …; view/URL …; template …; command …
- **Phụ thuộc:** tính năng/mô-đun nào, qua hàm nào
- **Kiểm chứng tự động:** file test + test end-to-end
- **Kiểm chứng tay:** lệnh hoặc thao tác trên trình duyệt
- **Nợ liên quan:** D-xxx
-->

## Lộ trình dự kiến (chưa làm — thứ tự có thể đổi khi duyệt)

| Mã dự kiến | Tính năng | Phục vụ |
|---|---|---|
| F-003 | Làm giàu: số contributor, tổ chức đứng sau, xác minh tổ chức, quốc gia | tìm đúng |
| F-004 | Ưu tiên repo Trung Quốc: tín hiệu location, README, danh sách tổ chức | tìm đúng |
| F-007 | Hồ sơ nhu cầu người dùng + AI chấm mức liên quan (Gemini qua 9router) | tìm đúng |
| F-008 | Nguồn khám phá phụ Exa, Tavily | tìm đủ |
| F-009 | Thông báo rising star hằng ngày | rising star |
