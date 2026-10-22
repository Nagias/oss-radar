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
- [ ] F-002 Quét sâu (trả nợ D-003, D-004, D-005) — bắt đầu bằng đề xuất thiết kế để chủ dự án duyệt
