# OSS Radar

Công cụ chạy trên trình duyệt ngay tại máy (local) để quét GitHub, tìm repo mã nguồn mở **chất lượng** và
**tiềm năng**, không bỏ sót, không trùng lặp, sắp theo star và đề xuất repo hợp nhu cầu.
Mục đích đầy đủ (nguyên văn chủ dự án) nằm ở `CLAUDE.md`.

## Chạy lần đầu (Windows, PowerShell)

```powershell
uv sync                                  # cài thư viện đúng phiên bản trong uv.lock
copy .env.example .env                   # mở .env, điền GITHUB_TOKEN
uv run python manage.py migrate          # tạo CSDL trong thư mục data/
uv run poe dev                           # mở http://127.0.0.1:8000
```

## Lệnh hay dùng

| Lệnh | Làm gì |
|---|---|
| `uv run poe check` | Chạy toàn bộ kiểm tra (giống hệt CI) |
| `uv run poe fmt` | Tự sửa định dạng code |
| `uv run poe test` | Chạy test |
| `uv run poe test-live` | Test gọi GitHub thật (cần `GITHUB_TOKEN`) |
| `uv run python manage.py scan "<truy vấn>"` | Quét GitHub từ dòng lệnh |

## Tài liệu

- `CLAUDE.md` — luật làm việc (mục đích, nguyên tắc, đường đúng, đường cấm, quy trình).
- `docs/ARCHITECTURE.md` — kiến trúc và lý do chọn.
- `FEATURE_MAP.md` — bản đồ tính năng.
- `DEBT.md` — sổ nợ có chủ đích.
