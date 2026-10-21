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
- [ ] Walking skeleton F-001 trên nhánh `feat/f001-quet-github` (TDD)
- [ ] Chạy thật F-001 (dòng lệnh + trình duyệt)
- [ ] Ghi nợ của F-001 vào `DEBT.md`, cập nhật `FEATURE_MAP.md`
- [ ] Chủ dự án duyệt nền + chọn public/private → chạy `scripts/github_setup.ps1` (trả nợ D-002)
- [ ] Mở PR F-001, CI xanh, merge
