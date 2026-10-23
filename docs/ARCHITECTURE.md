# Kiến trúc OSS Radar

> **Trạng thái: ĐÃ DUYỆT** — nền QĐ-01…QĐ-13 do chủ dự án duyệt qua PR #1 (2026-10-21); QĐ-14 duyệt cùng
> thiết kế F-002 (2026-10-22); QĐ-15, QĐ-16 duyệt cùng thiết kế F-005 (2026-10-22). Quyết định mới được
> thêm vào cuối bảng, không xoá dòng cũ (đổi trạng thái thành "Thay bởi QĐ-xx").

Mục tiêu của tài liệu: giải thích **vì sao** chọn từng thứ, theo hệ quả vận hành (được gì, tốn gì,
rủi ro gì). Quy tắc làm việc hằng ngày ("làm việc X thì đi đường nào") nằm ở `CLAUDE.md`.

---

## 0. Bảng quyết định

| Mã | Hạng mục | Chọn | Trạng thái |
|---|---|---|---|
| QĐ-01 | Ngôn ngữ | Python 3.13 | Đã duyệt, đã dùng |
| QĐ-02 | Môi trường & phụ thuộc | uv + `uv.lock`, cache trong `.cache/uv` | Đã duyệt, đã dùng |
| QĐ-03 | Web framework | Django 5.2 LTS | Đã duyệt, đã dùng |
| QĐ-04 | Cơ sở dữ liệu | SQLite chế độ WAL, file trong `data/` | Đã duyệt, đã dùng |
| QĐ-05 | Giao diện | Template Django render phía máy chủ | Đã duyệt, đã dùng |
| QĐ-06 | Gọi dịch vụ ngoài | httpx, chỉ trong `integrations/<dịch vụ>/` | Đã duyệt, đã dùng |
| QĐ-07 | Kiểm thử | pytest + pytest-django + respx + pytest-cov (≥ 90%) | Đã duyệt, đã dùng |
| QĐ-08 | Chất lượng code | ruff (format + lint) + mypy strict + django-stubs | Đã duyệt, đã dùng |
| QĐ-09 | Một lệnh kiểm tra | `uv run poe check` (poethepoet) | Đã duyệt, đã dùng |
| QĐ-10 | CI & bảo vệ nhánh | GitHub Actions trên `windows-latest`, action ghim SHA, main chỉ nhận PR có CI xanh | Đã duyệt, đã bật (Nagias/oss-radar) |
| QĐ-11 | Việc nền & lịch hằng ngày | Huey + SqliteHuey | Thay bởi QĐ-14 (2026-10-22) |
| QĐ-12 | AI | Gemini qua 9router (chuẩn OpenAI), AI chỉ phân loại/đánh giá | Dự kiến — chưa cài |
| QĐ-13 | Nguồn khám phá phụ | Exa, Tavily | Dự kiến — chưa cài |
| QĐ-14 | Việc nền | Một luồng trong tiến trình web (`core/background.py`), trạng thái + nhịp sống trong CSDL | Đã duyệt 2026-10-22, đã dùng (F-002); câu "nơi duy nhất tạo luồng" sửa bởi QĐ-15 |
| QĐ-15 | Lịch hằng ngày, chạy bù | Bộ nhịp trong tiến trình web (`core/scheduler.py`) + `settings.SCHEDULED_JOBS`; mỗi lúc một việc | Đã duyệt 2026-10-22, đã dùng (F-005) |
| QĐ-16 | Nguồn số liệu star tăng | Lịch sử star chính thức của GitHub; ảnh chụp star chỉ làm radar, giữ 35 ngày | Đã duyệt 2026-10-22, đã dùng (F-005) |
| QĐ-17 | Chấm điểm, lọc star giả | Hàm thuần tính lúc hiển thị (không lưu điểm); "Nghi cao" ẩn chứ không xoá; hồ sơ chủ repo lưu ở kho, làm mới sau 30 ngày | Đã duyệt 2026-10-23 (thiết kế F-006), đã dùng (F-006) |

---

## 1. Bối cảnh và ràng buộc

- **Một người dùng**, chạy trên máy Windows 11 cá nhân, mở bằng trình duyệt tại `http://127.0.0.1:8765`.
- **Ổ C gần đầy**: dữ liệu, môi trường Python, cache đều nằm trong thư mục dự án trên ổ D.
- **Tài nguyên khan hiếm thật sự là hạn mức API**, không phải CPU:
  GitHub Search 30 lần gọi/phút (khi có token) và trả tối đa 1.000 kết quả cho một truy vấn;
  REST thường 5.000 lần/giờ; Gemini, Exa, Tavily tính theo quota hoặc tiền.
- **Người viết code chủ yếu là AI agent** → ưu tiên công nghệ nhiều tài liệu, có quy ước sẵn, và có máy
  bắt lỗi sớm (kiểu dữ liệu, lint, test) để agent bịa là bị chặn ngay.

---

## 2. Từng lựa chọn và hệ quả

### QĐ-01 — Python 3.13
- **Được:** thư viện crawl, AI, xử lý dữ liệu đầy đủ nhất; máy đã cài sẵn Python 3.13 bản python.org
  (không phải bản Store); bạn đã quen quy trình `.venv`.
- **Tốn:** chạy chậm hơn Go/Rust, nhưng nút thắt là hạn mức API nên không đáng kể.
- **Đã loại:** TypeScript/Node — hợp làm web nhưng hệ sinh thái crawl/AI mỏng hơn; nếu sau cần Python cho
  AI thì phải giữ hai ngôn ngữ.

### QĐ-02 — uv + `uv.lock`
- **Được:** `uv sync` dựng lại môi trường y hệt từ file khoá, trên máy bạn lẫn CI; cài nhanh. Cache đặt ở
  `.cache/uv` cùng ổ D với `.venv` nên uv dùng hardlink thay vì chép file → đỡ tốn dung lượng.
- **Tốn:** cache riêng cho dự án (vài trăm MB khi đủ thư viện).
- **Đã loại:** pip + `requirements.txt` — không khoá phiên bản của thư viện con, dễ xảy ra "máy này chạy,
  máy kia lỗi".

### QĐ-03 — Django 5.2 LTS
- **Được:** mỗi việc phổ biến đã có sẵn **một chỗ theo quy ước**: bảng dữ liệu ở `models.py`, đổi cấu trúc
  CSDL bằng migration tự sinh, đường dẫn ở `urls.py`, kiểm tra dữ liệu nhập bằng Form, việc chạy dòng
  lệnh bằng management command, test có CSDL riêng. Agent ít phải tự nghĩ cấu trúc → ít bịa.
- **Vì sao LTS chứ không phải 6.1 mới nhất:** LTS được vá bảo mật tới 04/2028, API ổn định, ví dụ và tài
  liệu nhiều nhất. Phần Django mà dự án dùng (model, view, form, template, command) gần như không đổi giữa
  các bản. Lên bản LTS kế tiếp (6.2, dự kiến 04/2027) bằng một PR riêng.
- **Tốn:** nặng hơn FastAPI một chút; khởi động khoảng 1 giây.
- **Đã loại:**
  - FastAPI: không có quy ước thư mục/ORM/migration → mỗi agent tự chế một kiểu, càng về sau càng loạn.
  - Next.js: cách làm thay đổi qua từng bản lớn (rủi ro bịa API cao); việc quét chạy lâu không hợp.
  - Ruby on Rails: quy ước mạnh nhất nhưng cài và chạy trên Windows rất cực.

### QĐ-04 — SQLite (WAL) trong `data/`
- **Được:** không cài, không chạy dịch vụ CSDL nào; sao lưu = chép một file; chế độ WAL cho phép vừa đọc
  trên web vừa ghi khi quét. Đủ sức cho hàng triệu dòng (repo + ảnh chụp star hằng ngày).
- **Tốn:** tại một thời điểm chỉ một tiến trình được ghi.
- **Rủi ro & lối thoát:** nếu sau này nhiều worker ghi song song → chuyển PostgreSQL; Django đổi bằng cấu
  hình + `migrate`, code ORM giữ nguyên.
- **Đã loại:** PostgreSQL ngay từ đầu — phải cài và giữ server chạy, thừa cho một người dùng.

### QĐ-05 — Template Django render phía máy chủ
- **Được:** không cần Node, không có bước build, không phải làm API riêng cho giao diện. Mọi trang là HTML
  do Django trả về, test được bằng test client của Django.
- **Khi cần tương tác** (lọc tại chỗ, cập nhật trạng thái quét không tải lại trang): thêm HTMX (một file JS),
  ghi thành quyết định mới trước khi thêm.
- **Đã loại:** React/Vue dạng SPA — gấp đôi lượng code (API + giao diện), gấp đôi chỗ để sai.

### QĐ-06 — httpx, một cửa ra ngoài `integrations/`
- Mỗi dịch vụ ngoài (GitHub, 9router, Exa, Tavily…) có đúng một thư mục client trong
  `integrations/<dịch vụ>/`. Ruff cấm `import httpx` ở mọi nơi khác.
- **Được:** một chỗ duy nhất đặt token, timeout, đếm hạn mức, thử lại; test chặn được mạng tuyệt đối.
  Client trả về kiểu dữ liệu riêng (dataclass), không trả JSON thô → phần còn lại không phụ thuộc định
  dạng của từng hãng.
- **Đã loại:** `requests` (không có timeout mặc định); SDK riêng của từng hãng (mỗi SDK một kiểu lỗi,
  khó giả lập khi test).

### QĐ-07 — Kiểm thử
- pytest + pytest-django. respx giả lập HTTP: một fixture **tự động chặn mọi request thật** trong test
  thường. Test gọi GitHub thật được đánh dấu `live`, chỉ chạy khi gọi riêng (`uv run poe test-live`).
- Dữ liệu giả lập lấy từ **phản hồi thật** của GitHub lưu lại (không tự bịa JSON).
- Độ phủ test tối thiểu 90%; thấp hơn là CI đỏ.
- **Tốn:** viết test chiếm khoảng 40–50% công sức mỗi tính năng. **Được:** agent sửa code về sau không
  phá ngầm tính năng cũ.

### QĐ-08 — ruff + mypy strict
- ruff: một công cụ cho cả định dạng và soát lỗi; bật các luật cấm `print`, cấm comment TODO/FIXME (đường
  tắt phải vào sổ nợ), cấm `import httpx` và đọc biến môi trường sai chỗ.
- mypy strict + django-stubs: agent gọi một hàm/thuộc tính không tồn tại là mypy báo đỏ trước khi chạy →
  chặn kiểu "bịa API" ngay từ máy.
- **Tốn:** phải khai báo kiểu cho mọi hàm (khoảng 10% công gõ).

### QĐ-09 — `uv run poe check`
- Một lệnh duy nhất chạy: kiểm định dạng → soát lỗi → kiểm kiểu → `manage.py check` → kiểm migration đã
  sinh đủ chưa → test + độ phủ. CI chạy **đúng lệnh này**, nên "máy mình xanh" = "CI xanh".
- **Đã loại:** Makefile — Windows không có `make` sẵn.

### QĐ-10 — CI và bảo vệ nhánh
- GitHub Actions chạy trên **windows-latest** để bắt đúng loại lỗi của máy thật: đường dẫn có dấu cách, mã
  hoá tiếng Việt (`PYTHONUTF8=1`).
- Action ghim theo **mã commit (SHA)** thay vì tag: tag có thể bị thay ruột (tấn công chuỗi cung ứng), SHA
  thì không.
- Nhánh `main`: chỉ nhận merge qua Pull Request khi job `check` xanh; cấm force-push, cấm xoá; áp dụng cả
  với chủ repo; chỉ cho squash-merge để mỗi PR là một commit trên main.
- **Tốn:** runner Windows chậm hơn Ubuntu 1–2 phút mỗi lần; với repo private, phút chạy Windows bị tính
  đắt hơn Linux trong hạn mức miễn phí; repo public thì không tính phí.
- **Ràng buộc gói GitHub Free:** bảo vệ nhánh chỉ bật được cho repo **public**. Repo **private** cần gói
  GitHub Pro (khoảng 4 USD/tháng). → Chủ dự án quyết định.

### QĐ-11 — Việc nền và lịch quét hằng ngày (đã thay bởi QĐ-14)
- Dự kiến dùng **Huey với SqliteHuey**: hàng đợi lưu trong file SQLite (không cần Redis), có lịch định kỳ
  kiểu crontab cho quét hằng ngày, có chế độ chạy ngay (`immediate`) để test.
- **Chưa cài ở nền**: bộ khung chỉ quét một trang (1–2 giây) nên chạy thẳng trong request là đủ — đây là
  nợ có ghi sổ (D-003). Huey hiện ở bản 3.x: phải tra tài liệu bản 3 trước khi dùng.
- Máy tắt đúng giờ quét thì lịch bị lỡ → khi app khởi động, nếu lần quét hằng ngày gần nhất đã quá 24 giờ
  thì chạy bù.
- **Đã loại:** Celery (cần Redis/RabbitMQ, không hỗ trợ Windows chính thức); Task Scheduler của Windows
  (lịch nằm ngoài code, không test được, không nằm trong git).

### QĐ-12 — AI qua 9router (dự kiến)
- Gọi qua 9router (`http://localhost:20128/v1`, chuẩn OpenAI) bằng httpx trong `integrations/llm/` → đổi
  model hay nhà cung cấp chỉ là đổi cấu hình.
- **Vai trò AI bị giới hạn:** (1) mở rộng truy vấn từ nhu cầu của bạn, (2) chấm mức liên quan và tính ứng
  dụng, (3) tóm tắt tiếng Việt. AI **không được tạo số liệu** (star, contributor, tổ chức đứng sau) —
  số liệu luôn lấy từ GitHub API. Mỗi đánh giá của AI được lưu kèm lý do và phiên bản prompt để kiểm lại.

### QĐ-13 — Exa, Tavily (dự kiến)
- Nguồn khám phá phụ: tìm các link `github.com/...` xuất hiện trong bài viết, blog (kể cả blog Trung Quốc)
  mà tìm kiếm của GitHub bỏ sót. Link tìm được đi qua **cùng một đường chuẩn hoá** bằng GitHub API như mọi
  nguồn khác, nên không thể lọt dữ liệu bịa hoặc trùng.

### QĐ-14 — Việc nền: một luồng trong tiến trình web (thay QĐ-11)
- **Chủ dự án chốt 2026-10-22** khi duyệt thiết kế F-002 (`docs/designs/2026-10-22-f002-quet-sau.md`).
- `core.background.submit(job, id)` đẩy việc vào **một** luồng nền ngay trong tiến trình web. Trạng thái,
  điểm dừng (từng lát) và **nhịp sống** (`heartbeat_at`, ghi ≤ 30 giây/lần) nằm trong CSDL.
- **Được:** không thêm thư viện, không thêm tiến trình — bạn vẫn chỉ chạy `uv run poe dev`. Mỗi lúc một việc
  ghi → hợp SQLite; hạn mức GitHub không bị hai việc tranh nhau.
- **Tốn / rủi ro:** tắt app (hoặc server tự khởi động lại khi sửa code) là việc dừng → nhận ra nhờ nhịp sống
  cũ, chuyển "Tạm dừng", bấm Tiếp tục chạy từ lát dang dở (tự chạy bù: nợ D-006, làm ở F-005).
- Mỗi lúc chỉ một lần quét trên **mọi** tiến trình (trang web lẫn `manage.py scan`): kiểm trong transaction
  (SQLite `IMMEDIATE` giữ khoá ghi) dựa trên nhịp sống.
- Ruff cấm `threading`/`concurrent.futures` ngoài `core/background.py`.


### QĐ-15 — Lịch hằng ngày chạy trong app, chạy bù khi mở (sửa một câu của QĐ-14)
- **Chủ dự án chốt 2026-10-22** khi duyệt thiết kế F-005 (`docs/designs/2026-10-22-f005-rising-star.md`).
- **Bộ nhịp** `core/scheduler.py`: một luồng hẹn giờ nhỏ, **không đụng CSDL**. Cứ 5 phút (và ngay khi
  khởi động), nếu luồng nền rảnh thì đẩy một việc "đến lượt chưa" vào `core.background`; đang bận thì bỏ
  qua nhịp đó. Việc "đến lượt chưa" gọi lần lượt các hàm khai trong `settings.SCHEDULED_JOBS` (đường dẫn
  hàm, giống `MIDDLEWARE`): hiện có tự chạy tiếp lần quét bị gián đoạn và lượt quét hằng ngày.
- **Chỉ bật ở tiến trình phục vụ web:** lệnh `runserver` của dự án (`core/management/commands/runserver.py`,
  vẫn gõ `uv run poe dev`) bật bộ nhịp trong `on_bind`, tức sau khi kiểm tra hệ thống và đã giữ được cổng.
  Tiến trình theo dõi file, `migrate`, test, `manage.py scan`/`daily` không bật. Không dùng
  `AppConfig.ready()` hay signal.
- **Mỗi lúc một việc:** view gửi việc bằng `background.submit_if_idle` (kiểm rảnh và xếp hàng trong một lần
  giữ khoá); luồng nền đang bận thì nút Quét/Tiếp tục/Chạy ngay bị khoá kèm nhãn việc đang chạy, không xếp
  hàng chờ (nằm chờ lâu thì nhịp sống cũ, bị coi là gián đoạn). Giữa các tiến trình vẫn dựa trên nhịp sống
  trong CSDL như QĐ-14.
- **Sửa QĐ-14:** nơi được tạo luồng là `core/background.py` **và** `core/scheduler.py`.
- **Được:** không thêm thư viện, không thêm chương trình; lịch nằm trong code, test được bằng đồng hồ giả.
- **Tốn / rủi ro:** chỉ quét khi app đang mở; mở app muộn thì quét bù ngay (báo cáo của ngày có sau
  khoảng 30 phút). Server phát triển tự khởi động lại khi sửa code thì lượt bị ngắt rồi tự nối lại (tối đa 3
  lần/ngày). Muốn chạy đúng giờ kể cả khi không mở app thì sau này gắn Task Scheduler của Windows vào lệnh
  `manage.py daily`.
- **Đã loại:** Task Scheduler của Windows (lịch nằm ngoài app, phải đăng ký bằng tay; chủ dự án chọn trong
  app); Huey (QĐ-11 cũ).

### QĐ-16 — Số star tăng lấy từ lịch sử star chính thức; ảnh chụp chỉ làm radar
- Từ 7/2026 GitHub khoá danh sách người bấm star; từ 2026-09-04 có endpoint lịch sử star
  (`/repositories/{id}/stargazers/history`): 1 lượt gọi cho số star từng ngày của vài tuần, gọi được cả khi
  không có token (hạn mức "core": 60 lượt/giờ không token, 5.000 có token).
- **Ảnh chụp star** (`features/catalog`, mỗi repo một dòng mỗi ngày, ghi khi lưu repo vào kho) chỉ dùng làm
  **radar rẻ** để chọn ứng viên; con số hiển thị cho người dùng luôn từ lịch sử chính thức, hoặc ghi rõ
  "ước lượng từ ảnh chụp, chưa xác minh".
- **Giữ 35 ngày** cho ảnh chụp và danh sách repo của lần quét hằng ngày: giữ mãi tốn ~1,4 GB/năm, giữ 35
  ngày ổn định ~130 MB; lịch sử dài hạn đã có ở GitHub.
- **Rủi ro:** endpoint còn mới, có thể đổi; khi hỏng, lượt vẫn quét và ghi ảnh chụp, ứng viên rơi vào mục
  "chưa xác minh".

### QĐ-17 — Điểm là hàm thuần tính lúc hiển thị; repo nghi star giả bị ẩn chứ không xoá
- **Công thức một chỗ:** `features/scoring/rules.py` — hàm thuần (không CSDL, không mạng), hằng số có tên.
  Mỗi điểm trả kèm từng thành phần và lời giải thích (nguyên tắc 6). `features/scoring/services.py` gom dữ
  kiện từ kho rồi gọi công thức.
- **Không lưu điểm:** trang Rising star vài trăm dòng, trang lần quét tối đa 500 dòng → tính lúc xem chỉ
  vài mili giây. Được: đổi trọng số có hiệu lực ngay, không migration, không có điểm "cũ" lệch công thức.
  Tốn: không sắp/lọc toàn kho theo điểm bằng CSDL được — khi làm trang duyệt toàn kho (D-007) sẽ xét lại.
- **Ẩn chứ không xoá:** repo "Nghi cao" (≥ 60 điểm cộng dồn) chỉ bị đưa khỏi bảng chính, có nút "Hiện" kèm
  lý do từng tín hiệu; không tín hiệu đơn lẻ nào đủ 60. Ngưỡng là hằng số chỉnh được.
- **Hồ sơ chủ repo:** bảng `OwnerProfile` ở `features/catalog` (một dòng mỗi chủ, khoá login viết thường),
  chỉ lấy cho rising star trong bước "Lấy hồ sơ chủ repo" của lượt hằng ngày, ngân sách 100 lượt/ngày (có
  token) hoặc 10 (không token), làm mới sau 30 ngày. Trang lần quét chỉ dùng hồ sơ đã có, không gọi thêm.
- **Chiều phụ thuộc:** `rising` → `scoring` → `catalog`; `discovery` → `scoring`. `scoring` không import
  `rising`/`discovery`; số tăng star do bên gọi truyền vào (`GrowthFacts`).
- **Đã loại:** lưu điểm vào cột của `Repository` (phải tính lại mỗi khi đổi công thức); phân tích từng tài
  khoản bấm star kiểu StarScout (GitHub đã khoá danh sách người bấm star từ 7/2026); AI chấm điểm (vi phạm
  nguyên tắc 1 — số liệu chỉ từ API chính thức).

---

## 3. Cấu trúc thư mục theo tính năng

```
config/                  Cấu hình Django (settings, urls gốc). Không chứa nghiệp vụ.
features/
  catalog/               LÕI "kho repo": bảng Repository, hàm ghi không trùng. Nơi duy nhất ghi bảng này.
  discovery/             F-002 Quét sâu (tính năng mẫu — mọi tính năng sau copy cấu trúc này)
    models.py            Bảng của tính năng
    services.py          Toàn bộ nghiệp vụ
    slicing.py           Logic thuần tách riêng (chia lát truy vấn) — không gọi mạng, không CSDL
    forms.py             Kiểm tra dữ liệu người dùng nhập
    views.py, urls.py    Lớp web mỏng: nhận request → gọi service → render
    templates/discovery/ Giao diện
    management/commands/ Lệnh dòng lệnh (cho lịch chạy và cho agent tự kiểm chứng)
    tests/               Test của riêng tính năng
  rising/                F-005 Rising star + quét hằng ngày (growth.py: hàm thuần tính star tăng)
  scoring/               F-006 Chấm điểm (rules.py: hàm thuần; services.py: gom dữ kiện, lấy hồ sơ chủ)
integrations/
  github/                Client GitHub (+ pacing.py: giãn nhịp, gọi lại, ngân sách). Không biết Django model.
core/
  background.py          Chạy việc nền một luồng (QĐ-14).
  scheduler.py           Bộ nhịp gọi việc định kỳ trong settings.SCHEDULED_JOBS (QĐ-15).
  management/commands/   Lệnh runserver của dự án: bật bộ nhịp khi đã giữ cổng.
templates/base.html      Khung trang chung
static/css/app.css       CSS chung
tests/                   Test toàn dự án (lính gác quy tắc: sổ nợ, bản đồ tính năng…)
docs/ARCHITECTURE.md     Tài liệu này
docs/designs/            Thiết kế từng tính năng (chủ dự án duyệt trước khi code)
docs/plans/              Kế hoạch thực thi từng tính năng
CLAUDE.md                Luật làm việc cho agent
FEATURE_MAP.md           Bản đồ tính năng (cập nhật cùng PR với tính năng)
DEBT.md                  Sổ nợ có chủ đích
```

**Chiều phụ thuộc (một chiều, không vòng):**

```
views / urls / management commands  →  services  →  models (của mình hoặc của catalog)
                                                 →  integrations/*
integrations/*  →  (không import features, không import Django model)
```

- Tính năng A dùng tính năng B **chỉ qua `B.services`** (ngoại lệ: được trỏ ForeignKey tới model của B).
- `features/catalog` là nơi duy nhất ghi bảng `Repository`.

---

## 4. Luồng dữ liệu đích của sản phẩm

```mermaid
flowchart LR
  subgraph Nguon[Nguồn khám phá]
    S1[GitHub Search<br/>chia lát truy vấn]
    S2[Trending / OSS Insight]
    S3[Exa, Tavily]
    S4[Danh sách tổ chức uy tín]
  end
  Nguon --> C[Ứng viên owner/repo]
  C --> N[Chuẩn hoá qua GitHub API<br/>khoá = github_id]
  N --> K[(Kho repo<br/>không trùng)]
  K --> E[Làm giàu: contributors,<br/>tổ chức, quốc gia, README]
  K --> SN[Ảnh chụp star hằng ngày]
  E --> SC[Chấm điểm Chất lượng + Tiềm năng<br/>công thức minh bạch]
  SN --> SC
  SC --> AI[AI chấm mức liên quan<br/>qua 9router]
  AI --> R[Đề xuất theo hồ sơ người dùng]
  SN --> RS[Báo rising star hằng ngày]
```

Đã làm (F-001 + F-002): **GitHub Search chia lát (đủ, vượt trần 1.000) → chuẩn hoá → kho repo không
trùng → hiển thị sắp theo star, kèm độ phủ.**

Đã làm (F-005): **ảnh chụp star hằng ngày → lọc thô ứng viên → xác minh bằng lịch sử star chính thức →
báo rising star; lượt quét hằng ngày tự chạy trong app.**

---

## 5. "Tìm đúng, tìm đủ" — kiến trúc chống rác (định hướng cho các tính năng sau)

- **Đủ:** chia lát truy vấn theo khoảng ngày tạo và khoảng star để vượt trần 1.000 kết quả/truy vấn; kết
  hợp nhiều nguồn; mỗi lát quét ghi lại "GitHub báo bao nhiêu / đã lấy bao nhiêu" để biết chỗ nào còn sót.
- **Không trùng:** khoá chính là `github_id` — không đổi khi repo đổi tên hay chuyển chủ.
- **Đúng:** số liệu chỉ từ API chính thức; điểm số có bảng giải thích từng thành phần; lọc rác bằng luật
  cứng trước (fork, archived, không có code, star tăng bất thường…), AI chỉ xếp hạng phần còn lại.
- **Ưu tiên repo Trung Quốc:** tín hiệu từ vị trí (location) của chủ repo/tổ chức, ngôn ngữ README, danh
  sách tổ chức uy tín (ví dụ Alibaba, Tencent, ByteDance, Baidu, Zhipu, DeepSeek, ModelScope, OpenBMB,
  Shanghai AI Lab). Danh sách là **dữ liệu cấu hình** bạn sửa được, không viết cứng trong code.

---

## 6. Điểm cần chủ dự án quyết

1. Repo GitHub **public** (bảo vệ nhánh miễn phí, ai cũng xem được code) hay **private** (cần GitHub Pro để
   có bảo vệ nhánh).
2. Tên dự án `oss-radar` (giao diện hiển thị "OSS Radar") có được không.
3. "Nguyên tắc thiết kế kiểu Dune" trong `CLAUDE.md` là cách Claude diễn giải (không tìm thấy nguồn định
   nghĩa chuẩn); nếu bạn có nguồn cụ thể thì sửa theo nguồn đó.
