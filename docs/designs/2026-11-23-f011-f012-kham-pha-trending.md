# Kế hoạch: Khám phá repo trending / đang lên theo góc nhìn của bạn + làm lại giao diện kiểu ElevenLabs

## Bối cảnh

Hiện nay OSS Radar đã tự quét, tự xác minh rising star và gắn nhãn AI, nhưng còn hai chỗ hở:

1. **Chưa có "trending" đúng nghĩa.** Bước lọc thô (`_screen` trong `features/rising/services.py`) loại mọi repo
   từ 1.000 star, nên repo lớn tăng hàng nghìn star mỗi tuần không bao giờ hiện ra.
2. **Tìm "đúng thứ mình cần" còn phải tự làm.** Bốn trang (Quét, Rising star, Kho repo, Theo dõi) tách rời. Mỗi lần
   muốn xem lại một tổ hợp lọc thì phải chọn lại từ đầu. Giao diện còn thô (1 file CSS 163 dòng, không có JS).

Đích đến: mở app là thấy ngay repo đang hot và đang lên, đúng mảng bạn quan tâm, trong một trang Khám phá gọn
đẹp kiểu ElevenLabs, và mở lại các bộ lọc yêu thích bằng một bấm.

## Những điều bạn đã chốt

| Điểm | Bạn chọn |
|---|---|
| Trending gồm repo nào | Mọi cỡ repo đã có trong kho, xác minh bằng lịch sử star chính thức của GitHub. Chưa thêm nguồn ngoài |
| Ngưỡng trending | Tăng ≥ 200 star trong 7 ngày **và** ≥ 2% so với 7 ngày trước. Ứng viên để xác minh: ước lượng ≥ 100 star và ≥ 1%. Xác minh tối đa 300 repo/ngày khi có token; không có token thì bỏ qua |
| "Phù hợp với bạn" | Góc nhìn đã lưu: bộ lọc + cách sắp + từ khoá, có tên, mở bằng một bấm. Không để AI chấm (giữ QĐ-18) |
| Bố cục | Gộp thành trang **Khám phá** có 3 tab Trending / Đang lên / Toàn kho, chung một ô tìm và một thanh lọc. Thanh bên trái: Khám phá, Quét, Theo dõi, rồi mục Góc nhìn |
| Tab mở đầu | Trending |
| Màu | Nền trắng, chữ và nút đen; tự chuyển tối khi máy để chế độ tối |
| Phông chữ | **Be Vietnam Pro**, đóng gói sẵn trong app, không tải từ mạng mỗi lần mở |
| Tương tác | JavaScript tự viết khoảng 100 dòng, không thư viện. Tắt JS thì trang vẫn dùng đủ |
| Báo cáo rising cũ | Giữ thành trang chi tiết từng lượt (`/rising/runs/<id>/`), mở từ trang Theo dõi |

Việc duyệt kế hoạch này được coi là duyệt thiết kế. Bước đầu tiên khi bắt tay làm là lưu nội dung thành
`docs/designs/2026-11-23-f011-f012-kham-pha-trending.md`, theo đúng quy trình ở mục 6 của `CLAUDE.md`.

## Quy trình chung (áp dụng cho cả 3 PR)

- Có 3 PR, làm theo thứ tự A, B, C. Mỗi PR đi trên nhánh riêng, viết test đỏ trước rồi mới viết code (TDD), và chỉ
  merge khi CI xanh và bạn đồng ý.
  - A: `chore/giao-dien-nen`
  - B: `feat/f011-trending`
  - C: `feat/f012-kham-pha`
- Mỗi PR có kế hoạch con riêng trong `docs/plans/`.
- Mỗi PR cập nhật trong cùng PR: `TASKS.md`, `FEATURE_MAP.md`, và nếu có thì `DEBT.md`, `docs/ARCHITECTURE.md`.
- Mã mới:
  - QĐ-20 (giao diện), QĐ-21 (tách module service), QĐ-22 (trending);
  - F-011 (trending), F-012 (Khám phá + Góc nhìn);
  - D-010 (JS chưa có test tự động).
- File `workflow-blueprint.html` ở gốc dự án vẫn để ngoài git, không đưa vào PR nào.

---

## PR A — Giao diện nền (không đổi hành vi)

**Mục đích:** dựng hệ giao diện mới (màu, chữ, nút, thanh bên) và áp lên mọi trang hiện có. Chưa đổi chức năng,
nên lỗi nếu có chỉ nằm ở giao diện, dễ khoanh vùng.

### 1. Hệ màu và thành phần
- Viết lại `static/css/app.css` trong một file, không có bước build. Thứ tự các phần: token → nền → khung trang →
  thành phần → phần riêng từng trang.
- Token sáng: nền `#fff`, chữ `#0a0a0a`, chữ phụ `#525252`, viền `#e5e5e5`, nút chính đen.
- Token tối được định nghĩa lại trong `@media (prefers-color-scheme: dark)`. Thêm `color-scheme: light dark` và thẻ
  `<meta name="color-scheme">`.
- Giữ tạm tên biến cũ (`--accent`, `--chip-bg`) làm bí danh để không vỡ chỗ chưa kịp đổi.
- Thành phần:
  - `button` mặc định thành nút viên thuốc đen; thêm `.btn-secondary`, `.btn-ghost`, `.btn-sm`;
  - ô nhập cao 36px; ô tìm lớn có gợi ý phím `/`;
  - `.chip`, `.chip-check` (dùng `:has(input:checked)`, ô tick gốc vẫn hiện để dự phòng);
  - `.tabs`; bảng viền mảnh bo 12px; `.repo-row`;
  - bảng giải thích điểm (`.score`) nổi lên bằng CSS thuần;
  - `.badge`, `.status-*`, `.card`, `.page-header`, `.empty`.

### 2. Phông Be Vietnam Pro
- Lưu vào `static/fonts/be-vietnam-pro/`:
  - 4 độ đậm 400, 500, 600, 700, định dạng woff2, chia theo bộ ký tự latin, latin-ext, vietnamese, khai `unicode-range`;
  - kèm `OFL.txt` (giấy phép).
- Trước khi tải, mình sẽ báo cho bạn tên file, nguồn và tổng dung lượng, và chỉ tải khi bạn đồng ý. Nguồn là bản
  phát hành chính thức của Be Vietnam Pro (giấy phép OFL).
- Ghi kích thước và mã SHA-256 của file vào QĐ-20.
- Khai `@font-face` với `font-display: swap`. Thứ tự phông: `"Be Vietnam Pro", system-ui, "Segoe UI", sans-serif`.
  Thêm `preload` cho độ đậm 400.

### 3. Khung trang mới trong `templates/base.html`
- Bố cục mới là `aside.sidebar` cộng `main`, cụ thể:
  - Thanh bên gồm thương hiệu, `nav` có `aria-label="Các trang chính"`, khối `{% block sidebar_extra %}` và một dòng chân.
  - JS nạp bằng `<script src="{% static 'js/app.js' %}" defer>`.
- Giữ nguyên các block `title`, `head_extra`, `content` và cách đánh dấu `aria-current`.
- Ở PR A giữ nguyên 4 mục điều hướng như cũ. Việc đổi tên và gộp trang để sang PR C.
- Máy tính: lưới `240px 1fr`, thanh bên đứng yên khi cuộn, nội dung rộng tối đa 1200px.
- Màn hình ≤ 768px: thanh bên thành thanh trên cùng, các mục là hàng viên thuốc cuộn ngang. Làm bằng CSS thuần.

### 4. Áp lên mọi trang
- Các trang: `discovery/home.html`, `scan_detail.html`, `rising/report.html`, `watch.html`, `watch_edit.html`, các
  phần con `_today`, `_watch_form`, `_pager`, `browse/repos.html`, `scoring/_score.html`, `_suspicion.html`,
  `taxonomy/_labels.html`.
- Chỉ thêm lớp CSS và bọc `<header class="page-header">`.
- Giữ nguyên chữ, tên ô, id, đích gửi form, thẻ tự tải lại, và các lớp test đang bám (`num`, `unverified-list`,
  `hidden-repos`, `status-*`, `badge-*`, `spark`, `<strong>tên</strong>`).

### 5. `static/js/app.js` (≤ 150 dòng, chỉ tăng cường thêm)
- Form có `data-autosubmit` tự gửi khi đổi ô chọn, ô tick hoặc ô số. Ô chữ vẫn gửi khi bấm Enter. Form luôn giữ nút
  gửi cho trường hợp tắt JS.
- Form có `data-clean-query` bỏ ô trống khỏi đường dẫn.
- Phím `/` đưa con trỏ vào ô có `data-search`, trừ khi đang gõ ở ô khác.
- Form có `data-confirm` hỏi lại trước khi gửi (dùng cho nút xoá góc nhìn ở PR C).
- Gỡ chip lọc **không cần JS**: mỗi chip là một đường dẫn do máy chủ dựng sẵn.

### 6. Làm test bớt mong manh, nhưng không kiểm ít đi
- Thêm `tests/html.py`, chỉ dùng `html.parser` có sẵn của Python, kèm `tests/test_html_helper.py`. Các hàm:
  `nav_links`, `buttons` (chữ, có bị khoá không, đích form), `table_headers`, `meta_refresh`, `details_open`.
- Phải viết lại ngay trong PR A:
  - 3 test điều hướng trong `features/rising/tests/test_views.py` (hàm `_nav` cắt chuỗi `<nav class="site-nav"`);
  - các khẳng định `>Chạy ngay</button>` và `>Chạy tiếp</button>`, chuyển sang `buttons()` để kiểm thêm cả trạng thái khoá.
- Các khẳng định khác giữ nguyên, vì phần HTML đó không đổi.

### 7. Test viết trước và giấy tờ
- Test mới `tests/test_layout.py`:
  - thanh bên có ở mọi trang và đúng một mục được đánh dấu;
  - `app.js` nạp kèm `defer`;
  - phông nạp từ `/static/`;
  - có thẻ `color-scheme`;
  - mọi form có `data-autosubmit` đều có nút gửi.
- Thêm vào `tests/test_guards.py`:
  - cấm đường dẫn `http(s)://` trong `src`, `<link href>`, CSS `url()` và `@import` ở `templates/` và `static/`;
  - `app.js` ≤ 150 dòng;
  - có file `OFL.txt`.
- QĐ-20 sửa câu "cần tương tác thì thêm HTMX" của QĐ-05. Ghi: JS tự viết tăng cường dần, không thư viện, không CDN,
  phông đóng gói sẵn; được gì, tốn gì; đã loại HTMX, Tailwind, Google Fonts.
- Cập nhật `docs/ARCHITECTURE.md`: QĐ-20 và cây thư mục ở mục 3.
- Thêm vào `CLAUDE.md`:
  - mục 3, dòng "Tương tác trên trang → thuộc tính `data-*` + `static/js/app.js`";
  - mục 4, dòng cấm tải tài nguyên từ mạng.
- `FEATURE_MAP.md`: thêm dòng "khung trang + hệ thiết kế" vào bảng mô-đun lõi.
- `DEBT.md`: D-010 "app.js chưa có test tự động, kiểm bằng trình duyệt mỗi PR".

---

## PR B — Dữ liệu trending (F-011), mở đầu bằng trả nợ D-009

**Mục đích:** lượt quét hằng ngày tính và xác minh cả repo lớn đang tăng mạnh. Không quét thêm lượt tìm kiếm nào,
vì dùng lại ảnh chụp star đã có của mọi repo trong 16 chủ đề theo dõi.

### 1. Trả nợ D-009 trước (các commit riêng)
1. Tách `features/rising/services.py` (1.670 dòng) thành các file con:
   - `_runner.py` chứa `_DailyRunner`;
   - `daily_run.py` chứa lịch chạy, vòng đời lượt và `classify_backlog_if_due`;
   - `report.py` chứa `daily_report`, `latest_*` và các dòng báo cáo;
   - `overview.py` chứa `today_status`, `watch_overview`, `daily_estimate`.
   - `services.py` chỉ còn là cửa công khai: liệt kê rõ từng tên được lấy ra từ các file con, kèm `__all__`.
   - Chuyển 6 chỗ `monkeypatch.setattr(services, …)` sang đúng file con đang đọc hằng số đó:
     `test_verify.py:82,83,170`, `test_owners.py:121,140`, `test_classify_step.py:96`.
   - Bằng chứng không đổi hành vi: toàn bộ test xanh và độ phủ test không giảm.
   - Ghi QĐ-21: tách module trong thư mục tính năng, `services.py` vẫn là cửa duy nhất.
2. D-009.2: `_screen` dùng `run.day` thay vì giờ đồng hồ, kèm test lượt vắt qua nửa đêm.
3. D-009.3: nhãn "Mới vào danh sách" so theo đúng ngưỡng đang lọc.
4. D-009.4: chuyển `RETENTION_DAYS` thành `catalog.services.SNAPSHOT_RETENTION_DAYS`; trang lần quét lấy số này thay vì viết cứng "35".
   Sau bước này, xoá các dấu `DEBT(D-009)` trong code và ghi "Đã trả" trong sổ nợ.

### 2. Quy tắc trending (hàm thuần trong `features/rising/growth.py`)
- `TRENDING_MIN_GAIN_7D = 200`, `TRENDING_MIN_PERCENT_7D = 2.0`.
- Ứng viên: `TRENDING_CANDIDATE_MIN_ESTIMATE_7D = 100`, `…_PERCENT_7D = 1.0`.
- `is_trending(stars_now, gain_7d)` và `is_trending_candidate(stars_now, estimate_7d)`. Khi số star 7 ngày trước ≤ 0
  thì coi như đạt mức %.
- Một repo dưới 1.000 star mà tăng ≥ 200 thì vừa "đang lên" vừa "trending".

### 3. Dữ liệu: mở rộng `RisingCheck` thay vì tạo bảng mới
- Lý do: hình dạng dữ liệu giống hệt (số tăng, chuỗi 30 ngày, cờ cảnh giác). Dùng lại được vòng xác minh, biểu đồ
  nhỏ và lời giải thích. `latest_gain_subquery` tự có số tăng của repo lớn cho tab Toàn kho.
- Migration `rising/0005_trending.py`, chỉ đổi cấu trúc, không điền dữ liệu cũ:
  - `RisingCheck.pool` có hai giá trị `rising` / `trending`, mặc định `rising` nên dữ liệu cũ vẫn đúng;
  - `RisingCheck.is_trending`;
  - `DailyRun.trending_budget`, `trending_calls_used`, `trending_candidate_count`, `trending_count`;
  - `DailyRun.Step.TRENDING = 7` (các bước chỉ so bằng, nên thêm vào an toàn).

### 4. Thay đổi lượt hằng ngày
- `_screen`: bỏ điều kiện `stars < 1000`, vẫn loại fork và repo lưu trữ.
  - Dưới 1.000 star: giữ quy tắc cũ, xếp vào nhóm `rising`.
  - Từ 1.000 star: dùng `is_trending_candidate`, xếp vào nhóm `trending`.
- `_verify` chỉ lấy nhóm `rising`. Đây là chỗ dễ lỗi nhất: nếu quên, 300 lượt của rising sẽ bị repo lớn ăn mất.
- Bước mới `_verify_trending`:
  - Dùng lại `_verify_rows`, được tổng quát hoá để nhận ngân sách và trường đếm riêng.
  - Ngân sách chốt một lần: `TRENDING_BUDGET_WITH_TOKEN = 300`, `TRENDING_BUDGET_ANONYMOUS = 0`. Không có token
    thì bỏ qua bước và ghi chú lý do.
  - Đếm từng lượt gọi. Xử lý Dừng, repo bị xoá (404), bị giới hạn và token sai giống hệt `_verify`.
- Thứ tự bước: VERIFY → TRENDING → OWNERS. Lượt cũ đang dừng ở VERIFY sẽ đi tiếp sang TRENDING.
- `_save_history` gán `is_trending` cho cả hai nhóm.
- Các chỗ đếm phải lọc theo nhóm:
  - `_report` đếm `rising_count` và `unverified_count` chỉ trong nhóm `rising`, và thêm `trending_count`;
  - `daily_report` chỉ lấy nhóm `rising`.
- Thêm `rising.services.latest_trending_repository_ids()`.
- Giao diện tạm (PR C sẽ thay):
  - ô "Chỉ trending" trên `/repos/`;
  - cột Trending ở lịch sử lượt trên trang Theo dõi;
  - lệnh `manage.py daily` in thêm số trending.

### 5. Chi phí
- Thêm tối đa 300 lượt gọi GitHub loại thường mỗi ngày. Tổng khoảng 700 lượt mỗi ngày, trong khi hạn mức là 5.000
  lượt mỗi giờ.
- Lượt quét ngày dài thêm khoảng 10,5 phút (từ 52 lên khoảng 63 phút).
- Không tốn thêm lượt tìm kiếm.
- Bảng `RisingCheck` tăng khoảng 300 dòng mỗi ngày. Bảng này chưa có cơ chế dọn, ghi là rủi ro để quyết sau.

### 6. Test viết trước
- `test_growth.py`: các mốc biên của trending, gồm 199/200 star, 1,99%/2%, số star trước ≤ 0, và mốc ứng viên.
- `test_trending.py` mới, kiểm các trường hợp:
  - repo lớn vào nhóm trending; fork và repo lưu trữ bị loại; nhóm dưới 1.000 không đổi;
  - ngân sách rising không bị tiêu cho nhóm trending; ngân sách trending tách riêng và đếm từng lượt;
  - hết ngân sách thì có ghi chú;
  - Dừng rồi chạy tiếp không gọi lại repo đã xác minh;
  - repo bị xoá (404); không có token;
  - lượt cũ đang ở VERIFY chạy tiếp được;
  - repo 800 star tăng 250 thì có cả hai nhãn.
- `test_report.py`: số đếm báo cáo rising không đổi khi có dòng trending. Đây là test chặn lỗi lẫn nhóm. Kèm test cho
  D-009.3.
- Thêm test ở browse (`trending_only`, sắp theo số tăng hiện cả repo lớn) và ở e2e (`manage.py daily` với repo lớn giả lập).
- `tests/test_live_github.py`: gọi `star_history` thật trên một repo hơn 100.000 star.

### 7. Giấy tờ
- `FEATURE_MAP.md`: thêm F-011; cập nhật F-005 và F-010.
- QĐ-21; QĐ-22 (ngưỡng, ngân sách, chung bảng `RisingCheck`, sửa QĐ-16).
- D-009 ghi "Đã trả".

---

## PR C — Trang Khám phá và Góc nhìn (F-012)

**Mục đích:** một trang duy nhất để tìm repo trending, đang lên hoặc cả kho theo nhu cầu của bạn, kèm lưu bộ lọc yêu thích.

### 1. Đường dẫn (thuộc `features/browse/`; browse đọc rising qua `services`, rising không import browse)

| Đường dẫn | Nội dung |
|---|---|
| `/` | Khám phá. `?tab=trending\|rising\|all`, mặc định `trending` |
| `/views/`, `/views/<id>/`, `/views/<id>/delete/` | Quản lý góc nhìn. Tạo, đổi tên, xoá chỉ nhận POST |
| `/scan/` | Trang Quét (trước đây ở `/`). `/scans/<id>/` giữ nguyên |
| `/repos/` | Chuyển tạm (302) sang `/?tab=all` kèm đủ tham số. `rising_only` thành tab rising, `trending_only` thành tab trending |
| `/rising/` | 302: có `?day=` thì sang trang chi tiết lượt của ngày đó; không có thì sang `/?tab=rising`, giữ nhóm và cách sắp |
| `/rising/runs/<id>/` | Trang chi tiết lượt, là thân báo cáo cũ (ứng viên chưa xác minh, "vì sao có mặt", ngưỡng lọc, số trending) |
| `/rising/watch/` | Theo dõi: trạng thái hôm nay, thẻ tóm tắt báo cáo mới nhất, lịch sử lượt có link sang chi tiết |

- Dùng chuyển hướng 302 (tạm), không dùng 301, để trình duyệt không nhớ cứng.
- `run_now` và `stop` quay về trang Theo dõi. Khi bị từ chối thì trả mã 409 ngay trên trang Theo dõi.
- `taxonomy/_labels.html` trỏ sang `/?tab=all&audience=…`.
- `rising/_pager.html` trỏ sang trang chi tiết lượt.

### 2. Ba tab, chung một ô tìm và một thanh lọc
- Ô lọc dùng chung: `q`, nhóm "Dành cho ai", nhóm "Làm được gì", ngôn ngữ, star tối thiểu và tối đa, ngày tạo,
  giấy phép thương mại, chưa phân loại, hiện repo nghi star giả.
- Bộ lọc đang bật hiện thành chip có dấu ✕ (đường dẫn gỡ do máy chủ dựng), kèm nút "Xoá tất cả".
- Chuyển tab thì giữ bộ lọc, nhưng đặt lại cách sắp và về trang 1.

| Tab | Tập repo | Cách sắp (mặc định đứng đầu) |
|---|---|---|
| Trending | `is_trending` của báo cáo mới nhất (`latest_report_run()`) | Tăng 7 ngày, % tăng 7 ngày, Star, Chất lượng |
| Đang lên | `is_rising` của cùng báo cáo | Tiềm năng, Tăng 7 ngày, %, Chất lượng, Mới tạo |
| Toàn kho | Cả kho, đường `browse.services.browse` có sẵn | Như hiện nay (star, fork, số tăng, chất lượng, mới tạo, mới đẩy code) |

- **Trending và Đang lên** (mỗi tab tối đa khoảng 600 dòng, do ngân sách xác minh giới hạn):
  - lọc trong cơ sở dữ liệu;
  - lấy số liệu tăng star qua hàm mới `rising.services.latest_report_checks(kind)`;
  - chấm điểm bằng `scoring.score_repositories(growth=…)`;
  - ẩn repo "Nghi cao" theo mức nghi tính trực tiếp, giống `daily_report`;
  - sắp xếp, rồi chia 25 dòng mỗi trang.
- **Toàn kho:** giữ đường cũ, 50 dòng mỗi trang.
- **Mỗi dòng repo hiện:** tên, mô tả, nhãn, số tăng +1/+7/+30 ngày, %, biểu đồ nhỏ, cờ cảnh giác, nhãn "Mới", dòng
  "Vì sao có mặt", điểm. Thêm hook `data-repo="{{ full_name }}"` để test dò đúng dòng.
- **Tìm kiếm:** tách tối đa 5 từ. Mỗi từ phải khớp tên, mô tả hoặc chủ đề (`topics__icontains`), các từ ghép bằng VÀ.
- **Dòng đầu trang:** ngày báo cáo và khoảng ngày UTC của số liệu. Nếu lượt hôm nay đang chạy thì có băng báo kèm
  link sang Theo dõi. Trang Khám phá không tự tải lại.
- **Trang trống:**
  - chưa có báo cáo;
  - trending khi không có token;
  - không có kết quả, kèm nút xoá bộ lọc;
  - dòng "N ứng viên chưa xác minh" kèm link sang trang chi tiết lượt.

### 3. Góc nhìn đã lưu
- Model `features/browse/models.SavedView` (migration đầu tiên của browse) gồm `name` (≤ 60 ký tự, không trùng
  khi không phân biệt hoa thường), `query` (≤ 1000), `position`, `created_at`, `updated_at`.
- Hàm thuần trong `browse/services.py`:
  - `canonical_query(filters)`: thứ tự ô cố định, giá trị nhiều lựa chọn được sắp, bỏ ô rỗng, bỏ giá trị mặc định,
    bỏ `page`, `scan`, `day`;
  - `filters_from_query(query)` đọc lại chuỗi qua chính `BrowseForm`.
- Kiểm tra bằng `SavedViewForm` cộng `BrowseForm`: chuỗi lọc lỗi thì từ chối, tối đa 50 góc nhìn.
- Các hàm service: `save_view`, `rename_view`, `delete_view`, `sidebar_views(current_query)`.
- Thanh bên lấy danh sách góc nhìn qua `features/browse/context_processors.py::sidebar` (lớp mỏng chỉ gọi
  `services`, khai trong `settings.TEMPLATES`). Template chỉ hiển thị, không chứa logic.
  - Thêm một dòng vào mục 3 của `CLAUDE.md` cho đường đi này.
- Trên trang Khám phá:
  - bộ lọc hiện tại chưa trùng góc nhìn nào thì có form "Lưu góc nhìn";
  - đang mở một góc nhìn mà đổi bộ lọc thì có nút "Cập nhật «tên»".
- Trang `/views/` cho đổi tên và xoá (xoá có hỏi lại).
- Thanh bên cuối cùng gồm: Khám phá, Quét, Theo dõi; mục Góc nhìn (danh sách cộng "Quản lý"). Trên điện thoại,
  góc nhìn thành hàng chip cuộn ngang.

### 4. Test viết trước
- `browse/tests/test_explore.py`:
  - tập repo của từng tab; bộ lọc chung áp ở mọi tab;
  - cách sắp từng tab và khi gặp cách sắp lạ;
  - tìm nhiều từ, tìm trong chủ đề;
  - ẩn và hiện repo nghi star giả; nhãn "Mới";
  - chưa có báo cáo; trang vượt giới hạn;
  - số câu truy vấn không tăng theo số dòng.
- `test_canonical.py`: lưu rồi đọc lại ra đúng bộ lọc; bỏ giá trị mặc định; thứ tự ổn định.
- `test_saved_views.py`:
  - tạo mới, trùng tên, tên rỗng, tên quá dài, chuỗi lọc lỗi, vượt giới hạn 50;
  - đổi tên, xoá; chỉ nhận POST; id không có thì trả 404.
- `test_context_processor.py`: đánh dấu góc nhìn đang mở; các trang không phải Khám phá.
- Test chuyển hướng `/repos/` và `/rising/`, kể cả có `?day=`.
- Các test báo cáo rising chuyển sang trang chi tiết lượt, dùng `tests/html.py`, chủ yếu là chuyển chỗ chứ không viết lại.
- `test_e2e.py` dùng `data-repo`.
- Test của discovery đổi đường dẫn sang `/scan/`.

### 5. Giấy tờ
- `FEATURE_MAP.md`: thêm F-012; sửa lối vào của F-002, F-005, F-010.
- `docs/ARCHITECTURE.md`: ghi chú context processor và cập nhật dòng "Đã làm" ở mục 4.

---

## Kiểm chứng (bước riêng ở cuối mỗi PR)

| Kiểm gì | Bằng cách nào | Đạt khi |
|---|---|---|
| Toàn bộ cổng kiểm tra | `uv run poe check` (lint, kiểu, test, độ phủ ≥ 90%) | Xanh, độ phủ không giảm |
| Gọi GitHub thật (PR B) | `uv run poe test-live` | Xanh, gồm cả `star_history` trên repo hơn 100.000 star |
| Chạy thật trên bản sao dữ liệu (PR B, C) | `git worktree` riêng, chép `data/oss_radar.sqlite3` vào, rồi `migrate` và `manage.py daily` | Ghi vào PR: số ứng viên trending, số đã xác minh, lượt gọi trên ngân sách, số phút tăng thêm, top 10 so tay với GitHub; số rising cùng cỡ với lượt 27/10 |
| Tốc độ trang (PR C) | Đo giờ chạy của 3 tab × mọi cách sắp, cộng `q="video agent"` và tổ hợp nhóm | Mỗi trường hợp ≤ 300 ms phía máy chủ, số truy vấn cố định |
| Độ nặng trang | Tải HTML của `/`, `/?tab=rising`, `/?tab=all` | Mỗi trang ≤ 150 KB; CSS + JS ≤ 25 KB; phông chỉ tải một lần |
| Giao diện thật | Trình duyệt trong app ở 1440×900 và 375×812, nền sáng và tối | Thanh bên thành thanh trên ở điện thoại; tab, gỡ chip, tự lọc, phím `/` chạy; lưu, mở lại, đổi tên, xoá góc nhìn chạy; link cũ `/repos/?language=Go` và `/rising/?day=2026-10-27` chuyển đúng; không có lỗi trong console; tắt JS vẫn lọc được bằng nút |
| Không đổi hành vi (PR A) | Toàn bộ test cũ xanh, cộng chụp màn hình từng trang | Mọi trang làm đúng việc cũ |

Phần chưa tự kiểm được: hiện không có. Mọi bước trên đều tự chạy được trên máy này. Việc tải phông chữ cần bạn
gật đầu một lần (mình sẽ báo tên file, nguồn và dung lượng trước).

## Rủi ro chính

- **Lẫn nhóm rising và trending** là lỗi dễ xảy ra nhất. Đã có test chặn riêng ở PR B.
- **Lịch sử star của repo cực lớn chưa từng được gọi thử.** Nếu GitHub không trả được, repo đó hiện "chưa xác minh"
  kèm số ước lượng, đúng cách QĐ-16 đang làm.
- **PR C chuyển khoảng 47 test báo cáo rising sang trang mới.** Bộ hàm `tests/html.py` từ PR A giúp việc này chủ yếu
  là chuyển chỗ.
- **Hiệu ứng chip dùng `:has()`.** Trình duyệt cũ vẫn thấy ô tick gốc, nên không mất chức năng.
- **`/rising/?min_gain=` không có tương đương ở Khám phá**, nên bị bỏ khi chuyển hướng. Muốn lọc theo ngưỡng thì
  vẫn làm được ở trang chi tiết lượt.
