# DEBT — sổ nợ có chủ đích

Nợ không có trong sổ thì **không được tồn tại**. Mỗi đường tắt phải trả lời đủ 4 câu: nợ gì, vì sao chấp
nhận, khi nào trả, quên trả thì sao.

**Luật**
- Mã nợ `D-NNN` tăng dần, không dùng lại.
- Chỗ trong code liên quan ghi comment `# DEBT(D-NNN): <một dòng>` (hoặc `{# DEBT(D-NNN): … #}` trong template).
- `tests/test_guards.py` làm CI đỏ khi: code nhắc mã nợ không có trong sổ, nhắc mã đã "Đã trả", hoặc sổ có
  mã trùng.
- Trả nợ: xoá dấu `DEBT(...)` trong code, đổi trạng thái thành "Đã trả" kèm ngày + PR, trong cùng PR.
- Comment `TODO`/`FIXME`/`HACK`/`XXX` bị ruff cấm — muốn ghi việc dở thì ghi vào đây.

## Bảng nợ

| Mã | Nợ | Trạng thái | Trả khi |
|---|---|---|---|
| D-001 | Chạy bằng máy chủ phát triển (`runserver`), `DEBUG` bật mặc định, không đăng nhập | Mở | Trước khi chạy thường trực hoặc mở ra mạng |
| D-002 | CI và bảo vệ nhánh `main` chưa bật trên GitHub | Đã trả (2026-10-21) | Đã bật trên `Nagias/oss-radar` |
| D-003 | Quét chạy đồng bộ ngay trong request web, chưa có việc nền | Đã trả (2026-10-22) | F-002: chạy nền qua `core.background` |
| D-004 | Mỗi lần quét chỉ lấy trang đầu (tối đa 100 repo nhiều star nhất) | Đã trả (2026-10-22) | F-002: chia lát vượt trần 1.000 |
| D-005 | Gọi GitHub một lần, lỗi là dừng — chưa thử lại, chưa giãn nhịp, chưa có ngân sách gọi API | Đã trả (2026-10-22) | F-002: `integrations/github/pacing.py` |
| D-006 | Tắt app giữa chừng thì lần quét chỉ chuyển sang Tạm dừng; phải bấm Tiếp tục bằng tay | Đã trả (2026-10-23) | F-005: bộ nhịp tự chạy tiếp lần quét bị gián đoạn |
| D-007 | Trang kết quả lần quét chỉ hiện 500 repo nhiều star nhất | Đã trả (2026-10-27) | F-010: trang Kho repo `/repos/?scan=<id>` |
| D-008 | 5 điểm nhỏ còn lại từ rà soát F-002 (tính dư lượt khi Dừng lúc chờ, lệch đồng hồ, lệnh in "0/None", lát gốc lỗi báo "còn sót", trạng thái `queued` cũ) | Đã trả (2026-10-23) | PR `fix/d008-diem-nho-f002` |
| D-009 | 4 điểm để sau của F-005 (services.py rising ~1.400 dòng, ngày của bước lọc thô, nhãn "Mới vào danh sách" theo ngưỡng mặc định, "35 ngày" viết cứng) | Mở | PR `fix/` riêng ngay sau F-006 |

## Chi tiết

### D-001 — Chế độ chạy local: `runserver` + `DEBUG` + không đăng nhập
- **Nợ gì:** web chạy bằng `manage.py runserver` (máy chủ dành cho phát triển), `DEBUG=true` là mặc định
  trong `.env.example`, không có trang đăng nhập.
- **Vì sao chấp nhận:** một người dùng, app chỉ nghe `127.0.0.1` (máy khác không truy cập được). Thêm
  waitress/whitenoise/đăng nhập lúc này là 2–3 thư viện và một bước cấu hình không mang lại gì.
- **Khi nào trả:** khi muốn app chạy thường trực (khởi động cùng Windows), hoặc mở cho máy khác trong mạng
  LAN/Internet truy cập.
- **Quên trả thì sao:** nếu mở ra mạng mà vẫn `DEBUG=true` → trang lỗi lộ cấu hình và đường dẫn; không đăng
  nhập → ai trong mạng cũng bấm quét được, tiêu quota GitHub của bạn.
- **Vị trí:** `config/settings.py` (`DEBUG`, `ALLOWED_HOSTS`), `.env.example`.

### D-002 — CI và bảo vệ nhánh chưa bật trên GitHub
- **Nợ gì:** workflow CI (`.github/workflows/ci.yml`) và cấu hình bảo vệ nhánh
  (`scripts/github/branch-protection.json`) đã viết sẵn từ commit đầu nhưng **chưa có hiệu lực** vì chưa
  có repo GitHub: máy chưa cài `gh`, và chủ dự án chưa chọn public/private.
- **Vì sao chấp nhận:** tạo repo cần tài khoản GitHub của chủ dự án và một quyết định chỉ họ đưa ra được.
  Trong lúc chờ: lệnh `uv run poe check` chạy được ở máy (giống hệt CI), settings.json chặn agent push
  thẳng `main`.
- **Khi nào trả:** ngay khi chủ dự án cài `gh`, đăng nhập và chọn public/private → chạy
  `scripts/github_setup.ps1`.
- **Quên trả thì sao:** không có lưới chặn cuối — một commit hỏng vẫn vào được `main`.
- **Vị trí:** `.github/workflows/ci.yml`, `scripts/github_setup.ps1`, `scripts/github/branch-protection.json`.
- **Đã trả (2026-10-21):** chủ dự án tạo repo public `Nagias/oss-radar` bằng `scripts/github_setup.ps1`.
  CI chạy xanh trên `main` (Windows, run 39637535039). `main` bắt buộc PR + job `check` xanh, áp dụng cả
  admin, cấm force-push và xoá nhánh, lịch sử thẳng, chỉ squash-merge.

### D-003 — Quét chạy đồng bộ ngay trong request web
- **Nợ gì:** bấm "Quét" thì trình duyệt phải chờ đến khi gọi GitHub và ghi CSDL xong; chưa có hàng đợi
  việc nền (Huey theo QĐ-11 chưa cài).
- **Vì sao chấp nhận:** bộ khung chỉ gọi GitHub một lần (1–2 giây). Thêm hàng đợi lúc này = thêm thư viện
  và một tiến trình worker phải giữ chạy, trong khi chưa có việc nào dài. Cấu trúc đã sẵn cho việc nền:
  lần quét có trạng thái riêng (`ScanRun.status`: chờ → đang quét → xong/lỗi), view chỉ gọi `run_scan`.
- **Khi nào trả:** khi làm F-002 Quét sâu (nhiều trang, nhiều lát truy vấn → vài phút), hoặc khi có bất kỳ
  việc nào chạy quá ~5 giây.
- **Quên trả thì sao:** quét lâu thì trình duyệt treo rồi hết thời gian chờ; người dùng tưởng app hỏng.
- **Vị trí:** `features/discovery/services.py` (`run_scan`).
- **Đã trả (2026-10-22, F-002):** bấm Quét chỉ tạo lần quét rồi đẩy vào luồng nền (`core/background.py`,
  QĐ-14); trang tiến độ tự cập nhật; đường quét đồng bộ `run_scan` đã bỏ.

### D-004 — Mỗi lần quét chỉ lấy trang đầu
- **Nợ gì:** chỉ lấy tối đa 100 repo nhiều star nhất của một truy vấn, trong khi GitHub có thể báo hàng
  chục nghìn kết quả (và chính GitHub chỉ trả tối đa 1.000 kết quả cho một truy vấn).
- **Vì sao chấp nhận:** bộ khung cần một luồng mỏng chạy thật từ đầu đến cuối; chia lát truy vấn để vượt
  trần 1.000 là cả một tính năng (F-002). Trang kết quả **nói thật** với người dùng: hiện cảnh báo "GitHub
  báo có X kết quả; mới lấy Y".
- **Khi nào trả:** F-002 Quét sâu.
- **Quên trả thì sao:** trái mục tiêu "không bỏ sót" — repo ít star nhưng tiềm năng (đúng loại bạn cần)
  nằm ngoài trang đầu sẽ không bao giờ được thấy.
- **Vị trí:** `features/discovery/services.py` (`_fetch_and_store`),
  `features/discovery/templates/discovery/scan_detail.html` (cảnh báo).
- **Đã trả (2026-10-22, F-002):** chia lát theo ngày tạo (và theo star khi chỉ còn một ngày) để mỗi lát
  ≤ 1.000 kết quả; trang báo độ phủ và liệt kê chỗ còn sót (lát bị cắt, chưa chắc đủ, lỗi).

### D-005 — Gọi GitHub một lần, lỗi là dừng
- **Nợ gì:** client không thử lại khi GitHub lỗi tạm thời (5xx, mất mạng chốc lát), không tự chờ khi hết
  lượt gọi, không có ngân sách số lần gọi cho mỗi lần quét.
- **Vì sao chấp nhận:** mỗi lần quét chỉ gọi 1 lần; lỗi thì lần quét ghi "Lỗi" kèm lý do rõ ràng, người
  dùng bấm quét lại là xong.
- **Khi nào trả:** F-002 Quét sâu (hàng trăm lần gọi mỗi lượt — một lỗi tạm thời không được làm hỏng cả
  lượt; phải giãn nhịp theo nguyên tắc 3 và 4 trong CLAUDE.md).
- **Quên trả thì sao:** lượt quét dài hỏng giữa chừng vì một lỗi vặt; dội request khi hết lượt có thể làm
  GitHub khoá token.
- **Vị trí:** `integrations/github/client.py` (`_get_json`).
- **Đã trả (2026-10-22, F-002):** `integrations/github/pacing.py` — giãn nhịp 2,1/6,1 giây + ngẫu nhiên,
  chờ hồi lượt (tối đa 5 phút), gọi lại 3 lần khi lỗi tạm thời, ngân sách lượt gọi cho mỗi lần quét.

### D-006 — Lần quét bị gián đoạn phải tiếp tục bằng tay
- **Nợ gì:** quét chạy trong luồng nền của app web; tắt app (hoặc server tự khởi động lại khi sửa code)
  thì lần quét dừng. Lần mở sau, app nhận ra nhờ nhịp sống cũ và chuyển nó sang "Tạm dừng (bị gián
  đoạn)" — nhưng không tự chạy tiếp.
- **Vì sao chấp nhận:** tự chạy tiếp khi app khởi động cần một cơ chế khởi động nền an toàn (không chạy
  khi `migrate`, khi test…), mà đúng cơ chế đó F-005 (lịch quét hằng ngày, chạy bù khi lỡ giờ) cũng cần.
  Làm một lần ở F-005 thay vì làm hai lần. Phần đã quét không mất: Tiếp tục chạy từ lát dang dở.
- **Khi nào trả:** F-005.
- **Quên trả thì sao:** lần quét lớn bị bỏ dở nếu người dùng không để ý nút Tiếp tục.
- **Vị trí:** `features/discovery/services.py` (`pause_stale_scans`).
- **Đã trả (2026-10-23, F-005):** bộ nhịp `core/scheduler.py` (bật trong lệnh `runserver` của dự án)
  cứ 5 phút gọi `resume_interrupted_scan`: lần quét tay "bị gián đoạn" trong 24 giờ qua được tự chạy
  tiếp, tối đa 3 lần mỗi lần quét. Lần quét bạn đã bấm Dừng, bị Ctrl+C hoặc hết ngân sách thì không
  tự chạy. Lần quét thuộc lượt hằng ngày do chính lượt hằng ngày nối lại.

### D-007 — Trang kết quả chỉ hiện 500 repo nhiều star nhất
- **Nợ gì:** quét sâu có thể lấy hàng nghìn repo, nhưng trang kết quả một lần quét chỉ in 500 repo nhiều
  star nhất (ghi rõ "đang hiện 500 trên N"). Toàn bộ vẫn nằm trong kho.
- **Vì sao chấp nhận:** in hàng nghìn dòng làm trang nặng, khó đọc; trang duyệt kho có lọc và phân trang
  là một tính năng riêng, chưa nằm trong F-002.
- **Khi nào trả:** khi làm trang duyệt kho (lọc theo star, ngôn ngữ, chủ đề; phân trang).
- **Quên trả thì sao:** repo ít star (đúng nhóm "tiềm năng") của lần quét lớn không xem được trên web,
  chỉ thấy qua lệnh hoặc CSDL.
- **Vị trí:** `features/discovery/views.py` (`RESULTS_SHOWN_LIMIT`),
  `features/discovery/templates/discovery/scan_detail.html`.
- **Đã trả (2026-10-27, F-010):** trang Kho repo `/repos/` duyệt toàn kho có lọc (nhóm, ngôn ngữ, star, ngày
  tạo, giấy phép, rising star) và phân trang; trang lần quét có link "Xem cả N repo của lần quét này ở Kho
  repo" (`/repos/?scan=<id>`). Trang lần quét vẫn in 500 repo đầu cho nhanh.

### D-008 — 5 điểm nhỏ còn lại từ rà soát F-002
- **Nợ gì:** agent rà soát cuối của F-002 chỉ ra 5 điểm nhỏ, ghi trong PR Nagias/oss-radar#2 nhưng chưa sửa:
  1. bấm Dừng đúng lúc đang chờ giãn nhịp thì lượt gọi đã bị trừ ngân sách mà không gọi (dư 1 lượt);
  2. đồng hồ máy lệch nhiều phút thì thời gian chờ GitHub hồi lượt tính sai (chờ thừa hoặc thiếu);
  3. lệnh `scan` in "0/None" khi GitHub chưa kịp trả tổng số kết quả;
  4. lát gốc lỗi mà chưa lấy được repo nào vẫn hiện "Xong nhưng còn sót" thay vì "Lỗi";
  5. dòng cũ thời F-001 còn trạng thái `queued` (không còn trong danh sách trạng thái).
- **Vì sao chấp nhận:** không làm sai số liệu hay mất dữ liệu; mỗi điểm chỉ tốn tối đa 1 lượt gọi hoặc làm
  một dòng chữ khó hiểu. Gộp vào một PR `fix/` riêng thì không làm loãng PR của F-005.
- **Khi nào trả:** một PR `fix/` ngay sau F-005.
- **Quên trả thì sao:** người dùng thỉnh thoảng thấy chữ hiển thị khó hiểu; ngân sách lệch 1 lượt.
- **Vị trí:** `integrations/github/client.py` (`_get_json`), `integrations/github/pacing.py`
  (`wait_for_rate_limit`), `features/discovery/management/commands/scan.py` (`_print_summary`),
  `features/discovery/services.py` (`_finish_all_slices`), `features/discovery/models.py` (`ScanRun.Status`).
- **Đã trả (2026-10-23, PR `fix/d008-diem-nho-f002`):**
  1. client chờ giãn nhịp xong mới trừ ngân sách (hết ngân sách thì báo ngay, không chờ);
  2. bộ giãn nhịp đọc giờ GitHub từ header `Date` và tính giờ chờ theo giờ đó;
  3. lệnh `scan` in "?" khi chưa có tổng;
  4. mọi lát đều lỗi, không lấy được repo nào → lần quét "Lỗi" với loại lỗi mới "GitHub lỗi hoặc mất kết
     nối" — vẫn bấm Tiếp tục được (token sai, truy vấn sai thì không);
  5. migration `discovery/0005` đóng các dòng `queued` cũ thành "Lỗi" kèm lý do.

### D-009 — 4 điểm để sau của F-005
- **Nợ gì:**
  1. `features/rising/services.py` dài khoảng 1.100 dòng: toàn bộ nghiệp vụ của lượt hằng ngày nằm một
     file, theo luật "nghiệp vụ ở services.py";
  2. bước lọc thô lấy "hôm nay" theo đồng hồ chứ không theo ngày của lượt: lượt bấm Chạy ngay lúc 23:50 mà
     bước lọc chạy sau 0:00 thì so mốc lệch một ngày, repo mới tạo có thể bị ước lượng thấp;
  3. nhãn "Mới vào danh sách" so với rising star của lượt trước theo ngưỡng mặc định (1.000 star, 50 star
     /7 ngày), không theo bộ lọc bạn đang chọn trên trang;
  4. câu "đã dọn sau 35 ngày" ở trang lần quét viết cứng số 35 (hằng `RETENTION_DAYS` nằm ở `rising`,
     mà `discovery` không được import `rising`).
- **Vì sao chấp nhận:** không làm sai số liệu chính (số star tăng luôn lấy từ lịch sử chính thức). Điểm 2 chỉ
  xảy ra khi lượt vắt qua nửa đêm; điểm 3 chỉ ảnh hưởng nhãn khi bạn đổi bộ lọc; điểm 1 là chuyện dễ đọc.
- **Khi nào trả:** một PR `fix/` riêng ngay sau F-006. (F-006 không trả: thiết kế đã duyệt giữ phạm vi
  chấm điểm; phần lấy hồ sơ chủ nằm ở `features/scoring` nên `rising/services.py` chỉ dài thêm bước gọi và
  phần đọc báo cáo có điểm — khoảng 1.400 dòng.)
- **Quên trả thì sao:** file khó đọc dần; thỉnh thoảng một repo mới bị lỡ khỏi danh sách ứng viên trong
  một ngày (ngày sau vẫn được xét); nhãn "Mới" hơi lệch khi lọc.
- **Vị trí:** `features/rising/services.py` (đầu file, `_screen`, `daily_report`),
  `features/discovery/templates/discovery/scan_detail.html`.
