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
- [ ] Code theo TDD, sổ sách (CLAUDE.md, ARCHITECTURE QĐ-15/16, FEATURE_MAP, DEBT trả D-006 + thêm D-008)
- [ ] Chạy thật (`manage.py daily`, trình duyệt, tắt app giữa chừng), `poe test-live`, PR
