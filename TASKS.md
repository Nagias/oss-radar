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

- [ ] Chủ dự án điền `GITHUB_TOKEN` (xác minh 300 repo/ngày thay vì 50, quét nhanh gấp ~3 lần)
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
- [ ] Chủ dự án duyệt thiết kế
- [ ] Kế hoạch, code theo TDD, sổ sách, chạy thật, PR
