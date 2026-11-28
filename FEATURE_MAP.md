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
| F-002 | Quét sâu: chia lát vượt trần 1.000 kết quả, chạy nền, ngân sách, giãn nhịp, dừng/tiếp tục, độ phủ | Chạy thật | `features/discovery/` | Web `/scan/`, `/scans/<id>/`, nút Dừng/Tiếp tục; lệnh `manage.py scan` | `features/discovery/tests/test_deep_scan.py`, `test_e2e.py`, `test_auto_resume.py` | — |
| F-005 | Rising star + lượt quét hằng ngày: ảnh chụp star, lọc thô, xác minh bằng lịch sử star chính thức, lịch chạy trong app, chạy bù, tự chạy tiếp | Chạy thật | `features/rising/` | Web `/rising/watch/` (thẻ báo cáo mới nhất, lịch sử lượt), `/rising/runs/<id>/` (chi tiết lượt), tab Đang lên ở `/`, nút Chạy ngay/Chạy tiếp/Dừng; lệnh `manage.py daily`; tự chạy sau 7:00 khi app mở | `features/rising/tests/test_daily_run.py`, `test_verify.py`, `test_e2e.py` | — |
| F-006 | Chấm điểm Chất lượng / Tiềm năng có giải thích, lọc star giả (ẩn "Nghi cao", có nút hiện), hồ sơ chủ repo cho rising star | Chạy thật | `features/scoring/` | Cột điểm ở trang Khám phá `/`, chi tiết lượt `/rising/runs/<id>/` và `/scans/<id>/`; bước "Lấy hồ sơ chủ repo" của lượt hằng ngày | `features/scoring/tests/`, `features/rising/tests/test_owners.py` | — |
| F-010 | Phân loại repo theo nhóm bằng AI (Gemini qua 9router) + trang Kho repo lọc và sắp toàn kho | Chạy thật | `features/taxonomy/`, `features/browse/` | Web `/?tab=all` (tab Toàn kho của Khám phá); nhãn ở mọi bảng repo; lệnh `manage.py classify` | `features/taxonomy/tests/`, `features/browse/tests/` | — |
| F-011 | Trending mọi cỡ: repo từ 1.000 star (và repo nhỏ tăng mạnh) tăng ≥ 200 star và ≥ 2% trong 7 ngày, xác minh bằng lịch sử star chính thức, ngân sách riêng | Chạy thật | `features/rising/` | Bước 7 "Xác minh trending" của lượt hằng ngày; tab Trending ở `/` (Khám phá); cột Trending ở `/rising/watch/`; lệnh `manage.py daily` | `features/rising/tests/test_trending.py`, `test_growth.py` | — |
| F-012 | Trang Khám phá: 3 tab Trending / Đang lên / Toàn kho chung ô tìm (nhiều từ, cả chủ đề) và bộ lọc, chip gỡ từng ô; Góc nhìn đã lưu ở thanh bên | Chạy thật | `features/browse/` | Web `/` (`?tab=trending\|rising\|all`), `/views/`; thanh bên mục Góc nhìn; `/repos/`, `/rising/` cũ chuyển hướng 302 | `features/browse/tests/test_explore.py`, `test_saved_views.py`, `test_canonical.py`, `test_context_processor.py` | — |
| F-004 | Repo Trung Quốc — phần tìm: 10 truy vấn theo dõi tiếng Trung chạy cùng lượt hằng ngày (phần đánh dấu và ô lọc: gói 3 của bộ luật) | Phần tìm: chạy thật | `features/rising/` | Trang `/rising/watch/` (dòng 17–26, sửa / tắt được); lượt hằng ngày | `features/rising/tests/test_watch_seed_china.py` | — |
| F-013 | Phân loại bằng luật từ khoá, không cần AI — gói 1a: bộ từ khoá, hàm luật, lệnh đo so với nhãn AI (chưa ghi nhãn; ghi nhãn là gói 1b) | Gói 1a: đo được | `features/taxonomy/` | Lệnh `manage.py classify --compare-rules` (chỉ đọc) | `features/taxonomy/tests/test_rules.py`, `test_keywords.py`, `test_commands.py` | — |

## Mô-đun lõi và cửa ra ngoài

| Mô-đun | Vai trò | Ai được dùng | Test |
|---|---|---|---|
| `features/catalog/` | Lõi "kho repo": bảng `Repository` (khoá chống trùng `github_id`; có `open_issues` từ F-006), hàm `upsert_repositories` (ghi kèm ảnh chụp star `StarSnapshot` theo ngày); `baseline_snapshots`, `prune_snapshots`; hồ sơ chủ repo `OwnerProfile` (`save_owner_profile`, `mark_owner_missing`, `owner_profiles_for`, `logins_needing_profile`). Nơi DUY NHẤT ghi ba bảng này | Mọi tính năng, qua `features.catalog.services` | `features/catalog/tests/` |
| `integrations/github/` | Cửa ra GitHub REST API: `GitHubClient.search_repositories`, `GitHubClient.star_history` (lịch sử star theo `github_id`), `GitHubClient.get_user` (hồ sơ tài khoản), dataclass `GitHubRepo`/`RepoSearchPage`/`StarHistory`/`GitHubUser`, lỗi có tên (`GitHubRateLimitError`, `GitHubAuthError`…); `pacing.py`: giãn nhịp, chờ hồi lượt, gọi lại khi lỗi tạm thời, `CallBudget` | Service của các tính năng, qua `get_github_client(sleep=, budget=)` | `integrations/github/tests/` |
| `integrations/llm/` | Cửa ra AI qua 9router (chuẩn OpenAI): `LlmClient.complete` (gửi `stream: false`, xin JSON), `ChatResult` (nội dung + token), lỗi có tên (`LlmAuthError`, `LlmRateLimitError`, `LlmUnavailableError`, `LlmResponseError`, `LlmNotConfiguredError`); giãn nhịp và ngân sách dùng lại `integrations/github/pacing.py` (QĐ-18). AI chỉ phân loại, không tạo số liệu | Service của các tính năng, qua `get_llm_client(sleep=, budget=)`, `llm_configured()` | `integrations/llm/tests/` |
| `core/` | Hạ tầng dùng chung, không phải tính năng: `core.background` chạy việc nền trên MỘT luồng trong tiến trình web (`submit`, `submit_if_idle`, `busy_label`, `relabel` — QĐ-14); `core.scheduler` bộ nhịp gọi `settings.SCHEDULED_JOBS` (QĐ-15); lệnh `runserver` của dự án bật bộ nhịp. Chỉ hai file này được tạo luồng | View và lệnh của các tính năng | `core/tests/` |
| `templates/base.html` + `static/` | Khung trang chung (thanh bên trái, phần đầu trang) và hệ thiết kế (QĐ-20): `static/css/app.css` token sáng/tối + thành phần (nút, ô nhập, chip, tab, bảng, nhãn, điểm nổi); `static/css/fonts.css` + `static/fonts/be-vietnam-pro/` phông đóng gói sẵn; `static/js/app.js` tăng cường dần (tự lọc, bỏ ô rỗng, phím `/`, hỏi lại). Test HTML đọc theo ý nghĩa qua `tests/html.py` | Mọi template của tính năng (`{% extends "base.html" %}`) | `tests/test_layout.py`, `tests/test_guards.py`, `tests/test_html_helper.py` |

## Chi tiết từng tính năng

### F-013 — Phân loại bằng luật từ khoá (gói 1a)
- **Phục vụ vế nào của mục tiêu:** tìm đúng — repo mới vẫn có nhãn nhóm khi không có AI (tài khoản Gemini bị khoá
  2026-11-28); mỗi nhãn kèm lý do là danh sách từ khoá đã khớp (nguyên tắc 6).
- **Người dùng làm gì → thấy gì:** gói 1a chưa đổi gì trên trang. Chạy `manage.py classify --compare-rules` để xem
  bảng từng nhóm: AI gắn / luật gắn / trùng / bắt được / đúng, và số repo luật không xếp được.
- **Luồng chạy:** `keywords.load_keywords()` đọc `keywords.toml` (từ mạnh 2 điểm, từ yếu 1 điểm, bảng suy "Dành cho
  ai" từ "Làm được gì") → `rules.classify_by_rules(repo, keywords, taxonomy)` (hàm thuần): khớp nguyên từ trên
  topic, tên repo, mô tả; chữ Hán khớp chuỗi con; một dấu hiệu chỉ tính điểm một lần; nhóm "Làm được gì" cần ≥ 2 điểm,
  tối đa 3; "Dành cho ai" cần ≥ 3 điểm (Lập trình viên ≥ 2), tối đa 2; không nhóm nào đủ điểm → `None` →
  `services.compare_rules_with_ai()` so với nhãn đang lưu.
- **Thành phần:** `features/taxonomy/keywords.toml` (sửa tay, có `version` riêng), `keywords.py` (`Keywords`,
  `GroupKeywords`, `parse_keywords`), `rules.py`, `checks.py` (`taxonomy.E002`), `services.rule_labels`,
  `services.compare_rules_with_ai`, cờ `--compare-rules` của lệnh `classify`.
- **Phụ thuộc:** bộ nhóm F-010 (`categories.toml`). Không gọi mạng, không ghi CSDL.
- **Số đo (2026-11-28, 39.830 repo có nhãn AI):** luật không xếp được 4,7%. Đạt mục tiêu 80 / 80: Video (93% / 80%),
  Ảnh (90% / 81%), Game (82% / 83%). Gần đạt: AI Agent (95% / 77%), Công cụ lập trình (80% / 76%). Nhóm nhỏ đúng
  70–82% nhưng chỉ bắt được 31–66% (AI hiểu theo nghĩa cả câu, luật chỉ thấy từ khoá). "Dành cho ai" (độ đúng):
  Nghiên cứu 94%, Lập trình viên 84%, Marketer 83%, Làm game 82%, Kinh doanh 79%, Sáng tạo 78%.
- **Kiểm chứng tự động:** `test_rules.py` (khớp nguyên từ, chữ Hán, điểm, trần 3 / 2, `None`, suy "Dành cho ai"),
  `test_keywords.py` (file thật, 13 kiểu file hỏng, E002), `test_commands.py` (bảng so sánh, không ghi gì).
- **Kiểm chứng tay:** `uv run python manage.py classify --compare-rules`.
- **Còn lại:** gói 1b — ghi nhãn do luật gắn (cột nguồn, chạy cho cả kho trong lượt hằng ngày).
- **Nợ liên quan:** không có.

### F-004 — Repo Trung Quốc (phần tìm)
- **Phục vụ vế nào của mục tiêu:** tìm đủ (mục tiêu gốc: "nghiên cứu nhiều hơn các repo đến từ Trung Quốc"; đo
  2026-11-28: chỉ ~10% kho có dấu hiệu Trung Quốc vì cả 16 truy vấn đầu đều là topic tiếng Anh).
- **Người dùng làm gì → thấy gì:** không làm gì thêm — lượt hằng ngày quét thêm 10 truy vấn: `智能体`, `大模型`, `提示词`,
  `topic:deepseek`, `topic:qwen`, `短视频`, `数字人`, `抖音`, `小红书`, `飞书` (nhãn mảng "Trung Quốc · …"), mỗi truy vấn từ
  20 star, mức quét 50 lượt gọi. Trang Theo dõi hiện chúng ở dòng 17–26, sửa / tắt như mọi truy vấn khác. Repo tìm
  được vào chung kho, cũng được xét rising / trending.
- **Luồng chạy:** migration dữ liệu `rising/0006_seed_china_watch_queries` (truy vấn đã có thì bỏ qua, vị trí nối sau
  số lớn nhất) → bước 1 của lượt hằng ngày (`_runner._rescan`) quét như mọi `WatchQuery`.
- **Thành phần:** chỉ dữ liệu, không đổi model hay code chạy.
- **Phụ thuộc:** F-005 (lượt hằng ngày), F-002 (quét sâu).
- **Kiểm chứng tự động:** `features/rising/tests/test_watch_seed_china.py`, `test_watch_seed.py`.
- **Kiểm chứng tay:** `uv run python manage.py scan "智能体" --min-stars 20 --budget 50`; mở `/rising/watch/`.
- **Còn lại (thiết kế `docs/designs/2026-11-28-f013-f015-bo-luat.md`):** gói 3 — hai mức "Tiếng Trung" / "Trung Quốc",
  nhãn trên dòng, ô lọc "Chỉ repo Trung Quốc".
- **Nợ liên quan:** không có.

### F-012 — Trang Khám phá và Góc nhìn đã lưu
- **Phục vụ vế nào của mục tiêu:** tìm đúng (một ô tìm nhiều từ khớp cả chủ đề, lọc nhóm / ngôn ngữ / star / giấy
  phép áp được cho repo trending và đang lên), không rác (ẩn "Nghi cao" tính kèm số tăng ở tab Trending / Đang lên),
  đỡ việc tay (góc nhìn đã lưu mở lại tổ hợp lọc yêu thích bằng một bấm).
- **Người dùng làm gì → thấy gì:**
  - Mở app (`/`) là thấy tab **Trending** của báo cáo mới nhất; chuyển tab **Đang lên** / **Toàn kho** giữ bộ lọc,
    đặt lại cách sắp và trang.
  - Gõ từ khoá (phím `/`), tick nhóm, chọn ngôn ngữ / star / ngày tạo / giấy phép; bộ lọc đang bật hiện thành chip
    có ✕ để gỡ riêng, kèm "Xoá tất cả".
  - Mỗi dòng Trending / Đang lên có số tăng +1/+7/+30 ngày, %, biểu đồ 30 ngày, cờ cảnh giác, nhãn "Mới", dòng "Vì
    sao có mặt", điểm có giải thích.
  - Đặt tên rồi bấm **Lưu góc nhìn**; góc nhìn hiện ở thanh bên (mục Góc nhìn), bấm là mở lại. Đổi bộ lọc khi đang mở
    một góc thì có nút "Cập nhật «tên»". Trang **Quản lý** (`/views/`) để đổi tên, xoá (có hỏi lại).
  - Báo cáo rising cũ thành trang chi tiết từng lượt (`/rising/runs/<id>/`), mở từ trang Theo dõi.
- **Luồng chạy:** view `explore` → `BrowseForm.filters()` → `services.explore`:
  - Toàn kho: `browse` (lọc + sắp trong CSDL, 50 dòng/trang, ẩn "Nghi cao" theo điểm lưu sẵn).
  - Trending / Đang lên: `_filtered` (lọc repo trong CSDL) → `rising.services.latest_report_rows(kind, repos)` (dòng
    đã xác minh của báo cáo mới nhất, đã chấm điểm kèm số tăng) → ẩn "Nghi cao" → sắp → 25 dòng/trang.
  - Góc nhìn: `filters.canonical_query` (thứ tự cố định, bỏ mặc định, bỏ `page` / `scan` / `view`) → `SavedView`;
    `SavedViewForm` kiểm tên (≤ 60 ký tự, không trùng kể cả khác hoa thường) và bộ lọc (qua `BrowseForm`), tối đa 50.
  - Thanh bên: `context_processors.sidebar` → `services.saved_views(current)` (QĐ-23).
- **Thành phần:** `features/browse/filters.py` (`BrowseFilters`, tab, cách sắp, `params`, `canonical_query`,
  `without`), `services.explore`, `tab_links`, `active_chips`, `save_state`, `saved_views`, `save_view`,
  `update_view`, `delete_view`; `models.SavedView` (migration `browse/0001`); templates `explore.html`,
  `_report_rows.html`, `_all_rows.html`, `views.html`; `rising.services.latest_report_rows`, `reported_run`,
  `DailyRun.has_report`; trang `rising/run_detail.html`.
- **Phụ thuộc:** F-010 (nhãn, Toàn kho), F-005 + F-011 (báo cáo rising / trending), F-006 (điểm, nghi star giả).
- **Đường cũ:** `/repos/?…` → `/?tab=all&…` (`rising_only` → tab Đang lên, `trending_only` → tab Trending);
  `/rising/?day=` → chi tiết lượt ngày đó (không có thì Theo dõi); `/rising/` → `/?tab=rising`. Đều 302.
- **Kiểm chứng tự động:** `features/browse/tests/test_explore.py` (tập repo từng tab, lọc chung, tìm nhiều từ, cách
  sắp, ẩn "Nghi cao", trang trống, chia trang, số câu truy vấn cố định, link tab, chip), `test_saved_views.py`,
  `test_canonical.py`, `test_context_processor.py`, `features/rising/tests/test_views.py` (chi tiết lượt, chuyển
  hướng), `test_report.py` (`latest_report_rows`).
- **Kiểm chứng tay:** mở `/`, chuyển tab, gõ "video agent", lưu góc nhìn, mở lại từ thanh bên.
- **Nợ liên quan:** D-010 (JS chưa có test tự động).

### F-011 — Trending mọi cỡ
- **Phục vụ vế nào của mục tiêu:** tìm đủ (repo lớn đang hot không còn bị bỏ qua vì trần 1.000 star), tìm đúng
  (ngưỡng % loại repo khổng lồ tăng chậm so với cỡ của nó).
- **Người dùng làm gì → thấy gì:** không làm gì thêm — lượt hằng ngày tự xét. Từ F-012 xem ở tab **Trending** của
  trang Khám phá (`/`); cột "+7 ngày" của tab Toàn kho có số cho cả repo lớn. Trang chi tiết lượt có dòng "N repo
  trending"; `/rising/watch/` có cột Trending (số repo · lượt gọi/ngân sách). Trang Khám phá (F-012) sẽ có tab riêng.
- **Luồng chạy:** bước 2 lọc thô (`_runner._DailyRunner._screen`) bỏ trần 1.000 star: dưới 1.000 → nhóm `rising`
  (luật cũ), từ 1.000 → nhóm `trending` nếu `growth.is_trending_candidate` (ước lượng ≥ 100 và ≥ 1%) → bước 3 xác
  minh rising (chỉ nhóm `rising`) → **bước 7 xác minh trending** (`_verify_trending`, dùng chung `_verify_rows`,
  ngân sách `TRENDING_BUDGET_WITH_TOKEN = 300`, không token thì bỏ qua và ghi chú; bị Dừng / GitHub chặn /
  từ chối token thì chỉ ghi chú rồi đi tiếp như bước hồ sơ chủ — không làm mất báo cáo rising của ngày) →
  `_save_history` gán
  `is_trending` (≥ 200 và ≥ 2%) cho cả hai nhóm → lập báo cáo ghi `trending_count`.
- **Thành phần:** `growth.is_trending`, `is_trending_candidate` (hàm thuần); `RisingCheck.pool`, `is_trending`;
  `DailyRun.trending_budget`, `trending_calls_used`, `trending_candidate_count`, `trending_count`,
  `Step.TRENDING = 7`; `services.latest_report_rows` (F-012, thay `latest_trending_repository_ids` và ô `trending_only`).
- **Phụ thuộc:** như F-005; `browse` đọc `rising.services.latest_trending_repository_ids`.
- **Kiểm chứng tự động:** `features/rising/tests/test_trending.py` (lọc thô 2 nhóm, ngân sách không lẫn, hết ngân
  sách, Dừng rồi chạy tiếp, 404, không token, lượt dừng ở bước xác minh đi tiếp, repo nhỏ vừa rising vừa
  trending), `test_growth.py` (mốc biên 200 star / 2%), `test_report.py` (báo cáo `/rising/` không lẫn dòng
  trending), `features/browse/tests/`. Gọi GitHub thật: `uv run poe test-live` (lịch sử star của repo > 100.000 star).
- **Kiểm chứng tay:** chạy `manage.py daily` rồi mở `/` (tab Trending của trang Khám phá, F-012).
- **Nợ liên quan:** không có. `RisingCheck` không được dọn theo ngày (tăng ~950 dòng/ngày cả hai nhóm) — xem rủi ro QĐ-22.

### F-010 — Phân loại repo theo nhóm bằng AI, trang Kho repo
- **Phục vụ vế nào của mục tiêu:** tìm đúng (lọc đúng mảng mình cần thay vì một danh sách trộn lẫn), không rác
  (ẩn "Nghi cao" trên cả kho, lọc giấy phép cho phép dùng thương mại).
- **Người dùng làm gì → thấy gì:**
  - Mở tab **Toàn kho** của trang Khám phá (`/?tab=all`, F-012; `/repos/` cũ chuyển hướng), tick nhóm "Dành cho
    ai" / "Làm được gì" (mỗi nhóm có số repo).
  - Lọc thêm theo từ khoá, ngôn ngữ, star, ngày tạo, giấy phép thương mại, chỉ rising star, chưa phân loại.
  - Sắp theo star, fork, tăng 7 ngày, Chất lượng, mới tạo, mới đẩy code; 50 repo/trang.
  - Mỗi dòng có nhãn: bấm nhãn = lọc theo nhãn đó, di chuột = lý do AI xếp.
  - Trang Rising star có nhãn và ô lọc nhóm.
  - Trang lần quét có nhãn và link "Xem cả N repo của lần quét này ở Khám phá" (tab Toàn kho).
- **Luồng chạy:**
  - **Phân loại:** `taxonomy.services.repositories_needing_labels` (repo chưa có nhãn hoặc được quét lại có mô tả
    đổi) → `classify` (lô 40 repo, `prompt.build_messages` → `LlmClient.complete` → `prompt.parse_labels` kiểm
    đầu ra → lưu `RepoClassification` + `RepoLabel` ngay sau mỗi lô).
  - **Ba lối chạy:**
    - bước 5 "Phân loại repo" của lượt hằng ngày: repo của lượt, rising trước, ≤ 5 lượt gọi; hỏng thì ghi chú,
      vẫn lập báo cáo;
    - việc định kỳ `rising.services.classify_backlog_if_due`: sau khi lượt hôm nay xong, ≤ 10 lượt mỗi nhịp,
      ≤ 150 lượt/ngày, nghỉ 30 phút sau lỗi;
    - lệnh `manage.py classify` (phân loại bù, `--reclassify` sau khi đổi bộ nhóm).
  - **Trang Kho repo:** `browse.services.browse` lọc / sắp trong CSDL (nhãn qua `taxonomy`, điểm lưu sẵn qua
    `scoring.with_cached_scores`, rising / tăng 7 ngày qua `rising`, lần quét qua `discovery`); 50 dòng đang hiện
    mới chấm điểm trực tiếp.
- **Thành phần:**
  - `integrations/llm/` (client AI);
  - `features/taxonomy/`: `categories.toml` (bộ nhóm, sửa tay), `categories.py`, `prompt.py` (hàm thuần),
    `services.py`, model `RepoClassification` / `RepoLabel` / `ClassifyRun`, lệnh `classify`, template con
    `taxonomy/_labels.html`, check `taxonomy.E001`;
  - `features/browse/`: form `BrowseForm`, `services.browse`, view `repos`, `browse/repos.html`;
  - `features/scoring`: `ScoreCache`, `refresh_scores`, lệnh `rescore` (QĐ-19);
  - `features/rising`: bước `CLASSIFY` (số 6), `DailyRun.ai_calls_used`, `classify_backlog_if_due`, ô lọc nhóm.
- **Phụ thuộc:** `rising` → `taxonomy` → `catalog`; `browse` → `taxonomy`, `scoring`, `rising`, `discovery`,
  `catalog`; `taxonomy` không import `rising`/`discovery`.
- **Kiểm chứng tự động:**
  - `integrations/llm/tests/`;
  - `features/taxonomy/tests/` (bộ nhóm, prompt + câu chèn lệnh, gom lô, không gọi lại, thử lại, lệnh);
  - `features/browse/tests/` (mọi ô lọc, HOẶC / VÀ, sắp, phân trang, ô sai, số câu truy vấn không tăng theo dòng);
  - `features/rising/tests/test_classify_step.py`, `features/scoring/tests/test_cache.py`;
  - gọi 9router thật: `uv run poe test-live`.
- **Kiểm chứng tay:** `uv run python manage.py classify --budget 5`; `uv run poe dev` rồi mở
  `http://127.0.0.1:8765/?tab=all`.
- **Nợ liên quan:** trả D-007.

### F-006 — Chấm điểm Chất lượng / Tiềm năng, lọc star giả
- **Phục vụ vế nào của mục tiêu:** không rác (lọc star giả), tìm đúng (xếp theo chất lượng/tiềm năng thay vì
  chỉ theo star); nguyên tắc 6 — mọi điểm mở ra xem được từng thành phần.
- **Người dùng làm gì → thấy gì:** mở tab Đang lên ở `/` hoặc trang chi tiết lượt → bảng rising star có 3 cột **Tiềm năng**, **Chất lượng**,
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
- **Kiểm chứng tay:** `uv run poe dev`, mở `http://127.0.0.1:8765/?tab=rising`, bấm vào điểm, bấm "Hiện" ở dòng
  đã ẩn; mở một lần quét bất kỳ.
- **Nợ liên quan:** không có nợ mới. D-007 (trang lần quét 500 repo) vẫn giữ; D-009 xem sổ nợ.

### F-005 — Rising star + lượt quét hằng ngày
- **Phục vụ vế nào của mục tiêu:** tiềm năng (repo dưới 1.000 star tăng nhanh), tìm đủ (mỗi ngày quét lại
  danh sách theo dõi nên repo mới không bị lỡ), không rác (cờ cảnh giác: dồn một ngày, repo rất mới, không
  mô tả).
- **Người dùng làm gì → thấy gì:** mở app sau 7:00 → lượt hằng ngày tự chạy (hoặc bấm **Chạy ngay**) →
  trang Theo dõi (`/rising/watch/`) hiện tiến độ ("đã xong k/16 truy vấn"), xong thì hiện bảng rising star: +1/+7/+30 ngày,
  tăng %, tuổi repo, biểu đồ 30 ngày, nhãn **Mới vào danh sách**, cờ cảnh giác, dòng "Vì sao có mặt" ghi
  nguồn và khoảng ngày UTC; mục "Ứng viên chưa xác minh" (ước lượng, ghi rõ; gập sẵn) và "Chưa đủ dữ
  liệu". Lọc nhanh theo star tối đa và mức tăng tối thiểu. Bảng rising (25 dòng/trang, ô `page`) và mục chưa
  xác minh (20 dòng/trang, ô `upage`) chia trang riêng; link chuyển trang giữ mọi ô lọc và trang của mục
  kia — trang mặc định ~130 KB trên CSDL thật (trước đó tới 1,35 MB, tự tải lại mỗi 10 giây khi lượt chạy). Trang `/rising/watch/`: thêm/sửa/tắt truy vấn theo dõi,
  ước lượng lượt gọi và thời gian mỗi ngày, lịch sử các lượt, nút **Chạy ngay / Chạy tiếp / Dừng**. Trong
  lúc lượt chạy, nút Quét ở trang chủ bị khoá kèm nhãn việc đang chạy.
- **Luồng chạy:** `core.scheduler` (bật trong `runserver`) cứ 5 phút → `rising.services.run_daily_if_due`
  (đóng lượt hôm trước còn dở, tự chạy tiếp lượt bị gián đoạn ≤ 3 lần, sau 7:00 chưa có lượt thì tạo) →
  `execute_daily_run`: bước 1 quét lại từng `WatchQuery` bằng `discovery.services.start_scan/execute_scan`
  (nguồn "hằng ngày") → bước 2 lọc thô bằng `catalog.services.baseline_snapshots` + `growth.estimate_gain_7d`
  → bước 3 xác minh bằng `GitHubClient.star_history` (ngân sách 300 lượt có token / 50 không token) →
  bước 7 xác minh trending (F-011) → bước 5 lấy hồ sơ chủ repo của rising star (F-006) → bước 6 phân
  loại repo của lượt bằng AI (F-010) → bước 4 lập báo cáo: đếm, dọn ảnh chụp và kết quả quét hằng ngày
  cũ hơn `catalog.services.SNAPSHOT_RETENTION_DAYS` (35) ngày (số bước là mã `DailyRun.Step`, không
  phải thứ tự chạy).
  Code nằm ở `_common.py`, `_runner.py`, `daily_run.py`, `report.py`, `overview.py`; `services.py` chỉ xuất lại
  tên và là cửa công khai duy nhất (QĐ-21).
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
  - view/URL (`app_name = "rising"`): `report` (`/rising/`, nay chỉ chuyển hướng), `run_detail` (`/rising/runs/<id>/`), `watch` (`/rising/watch/`), `watch_edit`
    (`/rising/watch/<id>/`), `run_now` (POST `/rising/run/`), `stop` (POST `/rising/runs/<id>/stop/`)
  - template: `rising/report.html`, `watch.html`, `watch_edit.html`, `_today.html`, `_watch_form.html`,
    `_pager.html`
  - lệnh: `manage.py daily` (chạy lượt của hôm nay ở tiền cảnh)
- **Phụ thuộc:** `discovery.services` (quét, tự chạy tiếp, dọn kết quả), `catalog.services` (ảnh chụp
  star), `integrations.github` (`star_history`), `core.background`, `core.scheduler`.
- **Kiểm chứng tự động:** `features/rising/tests/` — hàm thuần với phản hồi lịch sử star thật đã lưu; lượt
  hằng ngày với GitHub giả lập (quét lại, lọc thô, xác minh, hết ngân sách, repo bị xoá 404, bị gián đoạn
  rồi chạy tiếp, Dừng, sang ngày mới, lỗi token rồi Chạy tiếp); lịch (trước/sau 7:00, chạy bù, tối đa 3
  lần tự chạy tiếp); trang và lệnh (gồm chia trang báo cáo); `test_e2e.py` chạy `manage.py daily` trên 300 repo giả rồi mở trang chi tiết lượt.
  `features/discovery/tests/test_auto_resume.py` cho phần trả D-006. Gọi GitHub thật: `uv run poe test-live`.
- **Kiểm chứng tay:** `uv run poe dev`, mở `http://127.0.0.1:8765/rising/watch/` sau 7:00 (lượt tự chạy) hoặc
  bấm Chạy ngay; sửa một file `.py` giữa lúc chạy để server khởi động lại → khoảng 5 phút sau lượt tự nối.
- **Nợ liên quan:** D-009 đã trả (2026-11-24, cùng F-011).

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
- **Nợ liên quan:** D-007 đã trả ở F-010 (xem đủ cả lần quét ở Kho repo). D-008 đã trả (2026-10-23). D-006 đã trả ở F-005
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
| F-004 (gói 3) | Đánh dấu repo Trung Quốc bằng luật: hai mức "Tiếng Trung" / "Trung Quốc", nhãn, ô lọc (location của chủ repo: để F-003) | tìm đúng |
| F-013 (gói 1b) | Ghi nhãn do luật gắn: cột nguồn "luật" / "AI", chạy cho cả kho trong lượt hằng ngày | tìm đúng |
| F-014 | Lọc kết quả kém: repo đã đóng, bỏ hoang, ít star không tăng, lạc đề — ẩn mặc định, có lý do (gói 2) | không rác |
| F-015 | Điểm gợi ý và tab Gợi ý theo "Dành cho ai", tính bằng luật (gói 4) | tìm đúng |
| F-008 | Nguồn khám phá phụ Exa, Tavily | tìm đủ |
| F-009 | Thông báo rising star hằng ngày | rising star |
