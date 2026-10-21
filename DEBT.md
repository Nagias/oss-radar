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
| D-002 | CI và bảo vệ nhánh `main` chưa bật trên GitHub | Mở | Ngay khi có repo GitHub |

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
