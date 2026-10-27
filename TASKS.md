# TASKS — việc đang làm

## Dựng nền dự án (2026-10-21)

- [x] Khảo sát máy, tra cứu phiên bản thư viện và cú pháp cấu hình hiện hành
- [x] Đề xuất kiến trúc → `docs/ARCHITECTURE.md`
- [x] `CLAUDE.md` (mục đích nguyên văn, nguyên tắc kiểu Dune, đường đúng, đường cấm, lệnh, quy trình)
- [x] Khung `FEATURE_MAP.md`, sổ nợ `DEBT.md`
- [x] `.claude/settings.json` phân quyền 3 vòng (allow / ask / deny)
- [x] CI `.github/workflows/ci.yml` + cấu hình bảo vệ nhánh + script tạo repo
- [x] Khung Django + bộ kiểm tra chung (`uv run poe check` xanh)
- [x] Commit nền móng đầu tiên trên `main`
- [x] Walking skeleton F-001 trên nhánh `feat/f001-quet-github` (TDD)
- [x] Chạy thật F-001 (dòng lệnh + trình duyệt + `poe test-live`)
- [x] Ghi nợ của F-001 vào `DEBT.md` (D-003, D-004, D-005), cập nhật `FEATURE_MAP.md`
- [x] Chủ dự án chọn public → chạy `scripts/github_setup.ps1`, CI xanh trên `main` (trả nợ D-002)
- [x] Mở PR F-001 (Nagias/oss-radar#1), CI xanh
- [x] Chủ dự án duyệt nền → squash-merge vào `main` (commit `726fe2d`, 2026-10-21)

## Tiếp theo

- [ ] Chủ dự án tạo token GitHub fine-grained (chỉ đọc repo public), điền `GITHUB_TOKEN` vào `.env`
- [x] F-002 Quét sâu: thiết kế đã duyệt, kế hoạch, code theo TDD (xem mục dưới)

## F-002 Quét sâu (2026-10-22)

- [x] Thiết kế `docs/designs/2026-10-22-f002-quet-sau.md` — agent độc lập rà soát, chủ dự án duyệt
- [x] Kế hoạch `docs/plans/2026-10-22-f002-quet-sau.md`
- [x] Task 1–6: giả lập GitHub, giãn nhịp/thử lại/ngân sách, chia lát, chạy nền, vòng quét, trang web + lệnh
- [x] Sổ sách: CLAUDE.md, ARCHITECTURE (QĐ-14), FEATURE_MAP (F-002), DEBT (trả D-003/4/5, thêm D-006/7)
- [x] Chạy thật: lệnh (ai-video 404/404; ai-agent 4.616/4.618, 68 lượt), trình duyệt (Dừng/Tiếp tục, tắt app giữa chừng), `poe test-live` 2/2
- [x] Agent độc lập rà soát cả nhánh (0 nghiêm trọng, 3 quan trọng) — đã sửa và kiểm lại
- [x] PR Nagias/oss-radar#2, CI xanh, chủ dự án duyệt → squash-merge vào `main` (commit `76730c9`, 2026-10-22)

## Tiếp theo (sau F-002)

- [x] Chủ dự án chọn tính năng kế tiếp: F-005 rising star + quét hằng ngày (2026-10-22)

## F-005 Rising star + quét hằng ngày (2026-10-22, nhánh `feat/f005-rising-star`)

- [x] Đo thật: độ tươi số star của Search, endpoint lịch sử star mới, phân bố tăng star, 16 chủ đề gợi ý
- [x] Chủ dự án chọn lịch chạy trong app, chạy bù khi mở app
- [x] Thiết kế `docs/designs/2026-10-22-f005-rising-star.md` — agent độc lập rà soát, đã chốt 7 điểm
- [x] Chủ dự án duyệt thiết kế (2026-10-22)
- [x] Kế hoạch `docs/plans/2026-10-22-f005-rising-star.md` (9 task)
- [x] Code theo TDD: 8 task (client lịch sử star, ảnh chụp star, bộ nhịp, tự chạy tiếp D-006, hàm tính tăng star,
      lượt hằng ngày, lọc thô/xác minh/báo cáo, trang + lệnh `daily`) — mỗi task có agent độc lập rà soát
- [x] Sổ sách: CLAUDE.md, ARCHITECTURE (QĐ-15, QĐ-16), FEATURE_MAP (F-005), DEBT (trả D-006; thêm D-008, D-009)
- [x] Chạy thật trên CSDL thật (2026-10-23, không token): lượt tự chạy lúc 10:23 khi mở app; app khởi động lại
      giữa chừng → 10:30 tự nối tiếp; máy cạn bộ nhớ → lượt Lỗi (MemoryError) → `manage.py daily` chạy tiếp
      từ truy vấn 9, xong 16/16: 596 lượt Search, 50/50 lượt xác minh, 47 rising star; `poe test-live` 3/3
- [x] PR Nagias/oss-radar#3, CI xanh, chủ dự án duyệt → squash-merge vào `main` (commit `9553d54`, 2026-10-23)

## Tiếp theo (sau F-005)

- [x] Chủ dự án điền `GITHUB_TOKEN` (xác minh 300 repo/ngày thay vì 50, quét nhanh gấp ~3 lần)
- [x] PR `fix/d008-diem-nho-f002` trả D-008 (5 điểm nhỏ của F-002) — xem mục dưới
- [ ] Chủ dự án chọn tính năng kế tiếp trong lộ trình FEATURE_MAP (F-003 làm giàu, F-004 ưu tiên Trung Quốc,
      F-006 chấm điểm + lọc star giả…) → thiết kế → duyệt → kế hoạch → TDD

## Trả nợ D-008 (2026-10-23, nhánh `fix/d008-diem-nho-f002`)

- [x] Test đỏ trước cho 5 điểm (11 test mới), rồi sửa cho xanh
- [x] Ngân sách chỉ trừ khi thật sự gọi; giờ chờ theo đồng hồ GitHub (header `Date`); lệnh `scan` in "?";
      mọi lát lỗi → "Lỗi" nhưng vẫn Tiếp tục được; migration đóng dòng `queued` cũ
- [x] Sổ sách: DEBT (D-008 đã trả), FEATURE_MAP
- [x] `poe check` xanh (526 test, độ phủ 99,06%); `poe test-live` 3/3; migrate CSDL thật (0 dòng `queued`);
      quét thật `topic:indie-hacker` mức Nhanh: 29/29 repo, đúng 1/1 lượt gọi
- [x] PR Nagias/oss-radar#4, CI xanh, chủ dự án duyệt → squash-merge vào `main` (commit `0d59a9a`, 2026-10-23)

## F-006 Chấm điểm Chất lượng / Tiềm năng, lọc star giả (2026-10-23, nhánh `feat/f006-cham-diem`)

- [x] Đo thật: tỉ lệ fork/star toàn kho, 47 rising star, hồ sơ chủ repo, hiệu chỉnh ngưỡng nghi star giả
- [x] Chủ dự án chọn: ẩn mặc định repo nghi star giả (có nút hiện); lấy hồ sơ chủ chỉ cho rising star
- [x] Thiết kế `docs/designs/2026-10-23-f006-cham-diem.md` — tự rà soát với vai người làm theo, chốt 7 điểm
- [x] Chủ dự án duyệt thiết kế (2026-10-23)
- [x] Kế hoạch `docs/plans/2026-10-23-f006-cham-diem.md` (10 task)
- [x] Code theo TDD (task 1–9): `poe check` xanh — 673 test, độ phủ 99,07%
- [x] Sổ sách: ARCHITECTURE (QĐ-17), FEATURE_MAP (F-006), DEBT (D-009 dời sang PR `fix/` sau F-006)
- [x] `poe check` xanh (674 test, 99,07%); `poe test-live` 4/4; chạy thật trên CSDL thật (sao lưu
      `data/backup-truoc-f006-2026-10-23.sqlite3`, migrate, 20 lượt gọi hồ sơ chủ không token): khớp 3 ví dụ
      thiết kế — `genspark-claw` 75 Nghi cao (ẩn), `xop01` 50 Cần xem, `feder-cr/git-ai` không nghi; trang
      `/rising/` 46 dòng + 1 ẩn, trang lần quét #7 có cột điểm. Chạy thật lộ ra 2 điểm đã sửa: ưu tiên hồ sơ
      chủ của repo đang bị nghi; phần giải thích điểm tràn cột
- [x] Agent độc lập rà soát cả nhánh: 0 nghiêm trọng, 1 quan trọng (kẹt ở bước hồ sơ chủ thì mất báo cáo
      của ngày — đã sửa: bước này không còn chặn báo cáo), 7 nhỏ (sửa 4; còn lại ghi trong báo cáo)
- [x] PR Nagias/oss-radar#5, CI xanh, chủ dự án duyệt → squash-merge vào `main`

## F-010 Phân loại repo bằng AI, trang Kho repo (2026-10-27, nhánh `feat/f010-phan-loai-duyet-kho`)

- [x] Hỏi đáp với chủ dự án; thiết kế `docs/designs/2026-10-27-f010-phan-loai-duyet-kho.md` — đọc thử với vai
      người làm theo, chủ dự án duyệt (2026-10-27); đo thật 9router
- [x] Kế hoạch `docs/plans/2026-10-27-f010-phan-loai-duyet-kho.md` (9 task)
- [x] Code theo TDD (task 1–8)
- [x] Sổ sách: ARCHITECTURE (QĐ-18 thay QĐ-12, QĐ-19), FEATURE_MAP (F-010, `integrations/llm`), DEBT (D-007 đã trả)
- [x] Agent độc lập rà soát cả nhánh: 1 nghiêm trọng (một lô bị bộ lọc an toàn của AI chặn thì kẹt mãi —
      đã sửa: chia đôi lô hỏng tới khi cô lập repo hỏng), các điểm quan trọng/nhỏ đã sửa (thiết kế §16)
- [x] Chạy thật trên CSDL thật (sao lưu `data/backup-truoc-f010-2026-10-27.sqlite3`, migrate, `rescore`
      32.412 repo trong 4,4 giây): `classify --budget 1000` gắn nhãn 32.371 repo, 41 repo AI bỏ sót — 811 lượt
      gọi, 5,56 triệu token vào + 1,57 triệu token ra, 162 phút; chạy bù bằng code mới: 41/41 repo, 2 lượt gọi
- [x] Kiểm tay 30 repo ngẫu nhiên: 28 nhãn hợp lý, 2 lệch nhẹ (không sai hẳn)
- [x] Trang `/repos/` trên dữ liệu thật: mọi bộ lọc/sắp 0,06–0,15 giây, cả trang 0,16 giây; lọc nhóm, chỉ
      rising star, nhập sai (báo lỗi, bỏ qua ô), trang quá lớn (về trang cuối), màn hình điện thoại (không tràn
      ngang); trang lần quét có nhãn + link sang Kho repo; không lỗi console
- [x] Lượt hằng ngày 27/10 chạy thật (bấm "Chạy ngay", 52 phút): 580 lượt Search, 300 xác minh, 100 hồ sơ chủ,
      4 lượt gọi AI (trần 5), 268 rising star, 691 repo mới; phân loại dần tự chạy mỗi 5 phút (3 lượt/nhịp) →
      33.103/33.103 repo có nhãn, 268/268 rising star có nhãn
- [x] `poe check` xanh (817 test, độ phủ 98,65%); `poe test-live` 5/5 (GitHub + 9router)
- [x] PR Nagias/oss-radar#6, CI xanh, chủ dự án duyệt → squash-merge vào `main`

## Sửa: trang `/rising/` quá nặng (2026-10-27, nhánh `fix/rising-chia-trang`)

- [x] Đo trên bản sao CSDL thật: báo cáo 27/10 nặng 1.355 KB (bảng rising 262 dòng ~869 KB, mỗi dòng ~3,4 KB vì
      có giải thích điểm; 337 ứng viên chưa xác minh ~389 KB), báo cáo 23/10 nặng 737 KB
- [x] Test đỏ trước (service, form, trang) → chia trang: bảng rising 25 dòng/trang (`page`), mục chưa xác minh
      20 dòng/trang (`upage`, gập sẵn, mở sẵn khi đang lật trang của nó); link giữ mọi ô lọc
- [x] Đo lại: 27/10 còn 129 KB, 23/10 còn 125 KB; trình duyệt: lật trang hai mục, bộ lọc giữ nguyên, đánh số
      tiếp 26, 27…, không lỗi console
- [x] `poe check` xanh (825 test, độ phủ 98,66%)
- [x] PR Nagias/oss-radar#7, CI xanh, chủ dự án duyệt → squash-merge vào `main`
- [x] Kiểm thêm sau khi mở PR: giả lập lượt đang chạy trên bản sao CSDL → trang tự tải lại mỗi 10 giây,
      mỗi lần ~130 KB, giữ đúng trang và bộ lọc
