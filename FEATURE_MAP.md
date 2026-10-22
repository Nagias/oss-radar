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
| F-002 | Quét sâu: chia lát vượt trần 1.000 kết quả, chạy nền, ngân sách, giãn nhịp, dừng/tiếp tục, độ phủ | Chạy thật | `features/discovery/` | Web `/`, `/scans/<id>/`, nút Dừng/Tiếp tục; lệnh `manage.py scan` | `features/discovery/tests/test_deep_scan.py`, `test_e2e.py` | D-006, D-007 |

## Mô-đun lõi và cửa ra ngoài

| Mô-đun | Vai trò | Ai được dùng | Test |
|---|---|---|---|
| `features/catalog/` | Lõi "kho repo": bảng `Repository` (khoá chống trùng `github_id`), hàm `upsert_repositories`. Nơi DUY NHẤT ghi bảng này | Mọi tính năng, qua `features.catalog.services` | `features/catalog/tests/` |
| `integrations/github/` | Cửa ra GitHub REST API: `GitHubClient.search_repositories`, dataclass `GitHubRepo`/`RepoSearchPage`, lỗi có tên (`GitHubRateLimitError`, `GitHubAuthError`…); `pacing.py`: giãn nhịp, chờ hồi lượt, gọi lại khi lỗi tạm thời, `CallBudget` | Service của các tính năng, qua `get_github_client(sleep=, budget=)` | `integrations/github/tests/` |
| `core/` | Hạ tầng dùng chung, không phải tính năng: `core.background.submit(job, id)` chạy việc nền trên MỘT luồng trong tiến trình web (QĐ-14). Nơi duy nhất được tạo luồng | View và lệnh của các tính năng | `core/tests/` |

## Chi tiết từng tính năng

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
- **Nợ liên quan:** D-006 (tiếp tục bằng tay sau gián đoạn), D-007 (trang chỉ hiện 500 repo đầu).

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
| F-005 | Ảnh chụp star hằng ngày + phát hiện rising star + lịch quét hằng ngày | tiềm năng |
| F-006 | Chấm điểm Chất lượng/Tiềm năng có giải thích | không rác |
| F-007 | Hồ sơ nhu cầu người dùng + AI chấm mức liên quan (Gemini qua 9router) | tìm đúng |
| F-008 | Nguồn khám phá phụ Exa, Tavily | tìm đủ |
| F-009 | Thông báo rising star hằng ngày | rising star |
