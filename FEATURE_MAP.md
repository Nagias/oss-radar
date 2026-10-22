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
| F-001 | Quét GitHub theo truy vấn → lưu không trùng → xem sắp theo star | Bộ khung, chạy thật | `features/discovery/` | Web `/`, `/scans/<id>/`; lệnh `manage.py scan "<truy vấn>"` | `features/discovery/tests/test_e2e.py` | D-003, D-004, D-005 |

## Mô-đun lõi và cửa ra ngoài

| Mô-đun | Vai trò | Ai được dùng | Test |
|---|---|---|---|
| `features/catalog/` | Lõi "kho repo": bảng `Repository` (khoá chống trùng `github_id`), hàm `upsert_repositories`. Nơi DUY NHẤT ghi bảng này | Mọi tính năng, qua `features.catalog.services` | `features/catalog/tests/` |
| `integrations/github/` | Cửa ra GitHub REST API: `GitHubClient.search_repositories`, dataclass `GitHubRepo`/`RepoSearchPage`, lỗi có tên (`GitHubRateLimitError`, `GitHubAuthError`…) | Service của các tính năng, qua `get_github_client()` | `integrations/github/tests/` |
| `core/` | Hạ tầng dùng chung, không phải tính năng: `core.background.submit(job, id)` chạy việc nền trên MỘT luồng trong tiến trình web (QĐ-14). Nơi duy nhất được tạo luồng | View và lệnh của các tính năng | `core/tests/` |

## Chi tiết từng tính năng

### F-001 — Quét GitHub theo truy vấn (bộ khung đi được, TÍNH NĂNG MẪU)
- **Phục vụ vế nào của mục tiêu:** không trùng; sắp theo star. (Tìm đủ còn nợ D-004.)
- **Người dùng làm gì → thấy gì:** mở `http://127.0.0.1:8765` → gõ truy vấn kiểu GitHub (vd
  `topic:ai-agent stars:>100`) → bấm **Quét** → sang trang kết quả: bảng repo sắp theo star, nhãn **Mới**
  (lần đầu vào kho) / **Đã có** (đã biết từ trước), cảnh báo nếu GitHub còn nhiều kết quả chưa lấy. Lỗi từ
  GitHub (hết lượt, sai token, sai truy vấn, mất mạng) hiện thành câu tiếng Việt kèm chi tiết.
- **Luồng chạy:** `views.home` (POST) → `ScanForm` kiểm tra → `services.run_scan` → `get_github_client()
  .search_repositories` (1 trang, 100 repo, sắp theo star) → `catalog.services.upsert_repositories` (ghi
  không trùng theo `github_id`) → lưu `ScanRun` + `ScanResult` → redirect `views.scan_detail` →
  `services.scan_results` (sắp theo star) → template.
- **Thành phần:**
  - model: `ScanRun` (truy vấn, trạng thái chờ/đang quét/xong/lỗi, số liệu, lý do lỗi),
    `ScanResult` (repo nào trong lần quét nào, `is_new`)
  - service: `run_scan`, `recent_scans`, `scan_results` — `features/discovery/services.py`
  - form: `ScanForm` (truy vấn 1–256 ký tự) — dùng chung cho web và lệnh
  - view/URL: `home` (`/`), `scan_detail` (`/scans/<id>/`) — `app_name = "discovery"`
  - template: `discovery/home.html`, `discovery/scan_detail.html` (khung chung `templates/base.html`)
  - lệnh: `uv run python manage.py scan "<truy vấn>"`
- **Phụ thuộc:** `features.catalog.services.upsert_repositories`;
  `integrations.github.client.get_github_client`.
- **Kiểm chứng tự động:** `features/discovery/tests/` — service, form, view, lệnh; và
  `test_e2e.py` đi đúng đường người dùng: mở trang → quét → thấy sắp theo star → quét lại → không trùng.
  GitHub được giả lập bằng phản hồi thật đã lưu (`tests/fixtures/github/`).
  Gọi GitHub thật: `uv run poe test-live` (`tests/test_live_github.py`).
- **Kiểm chứng tay:** `uv run python manage.py scan "topic:ai-agent"` hoặc mở trình duyệt như trên.
- **Nợ liên quan:** D-003 (chạy đồng bộ), D-004 (chỉ trang đầu), D-005 (chưa thử lại khi lỗi).

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
| F-002 | Quét sâu: chia lát truy vấn vượt trần 1.000 kết quả, chạy nền (trả D-003, D-004, D-005) | tìm đủ |
| F-003 | Làm giàu: số contributor, tổ chức đứng sau, xác minh tổ chức, quốc gia | tìm đúng |
| F-004 | Ưu tiên repo Trung Quốc: tín hiệu location, README, danh sách tổ chức | tìm đúng |
| F-005 | Ảnh chụp star hằng ngày + phát hiện rising star + lịch quét hằng ngày | tiềm năng |
| F-006 | Chấm điểm Chất lượng/Tiềm năng có giải thích | không rác |
| F-007 | Hồ sơ nhu cầu người dùng + AI chấm mức liên quan (Gemini qua 9router) | tìm đúng |
| F-008 | Nguồn khám phá phụ Exa, Tavily | tìm đủ |
| F-009 | Thông báo rising star hằng ngày | rising star |
