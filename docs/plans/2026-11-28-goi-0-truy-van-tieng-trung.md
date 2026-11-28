# Gói 0 — Truy vấn theo dõi tiếng Trung (F-004, phần tìm): kế hoạch thực thi

> **Cho agent thực thi:** dùng superpowers:executing-plans. Bước dùng ô tick (`- [ ]`).

**Mục tiêu:** lượt quét hằng ngày tìm thêm repo Trung Quốc bằng 10 truy vấn mới, để kho không còn chỉ đến từ 16 chủ
đề tiếng Anh. Làm trước các gói khác để app bắt đầu tích ảnh chụp star hằng ngày cho nhóm repo này.

**Thiết kế:** `docs/designs/2026-11-28-f013-f015-bo-luat.md`, mục "Luật D" và "Gói 0".

## Ràng buộc

- Nhánh `feat/f004-truy-van-tieng-trung`. TDD: test đỏ trước. Không thêm thư viện, không đổi model.
- Migration dữ liệu mới, không sửa `0002_seed_watch_queries`. Truy vấn đã có thì bỏ qua (không bật lại, không sửa dòng
  chủ dự án đã chỉnh). `position` nối tiếp sau số lớn nhất đang có. Lùi migration không xoá gì.
- Mỗi truy vấn: từ 20 star, mức quét 50 lượt gọi, đang bật. Không viết `pushed:` vào truy vấn.

## Mười truy vấn

| Mảng (nhãn) | Truy vấn | Nghĩa |
|---|---|---|
| Trung Quốc · AI Agent | `智能体` | agent AI |
| Trung Quốc · AI Agent | `大模型` | mô hình lớn (LLM) |
| Trung Quốc · AI Agent | `提示词` | prompt |
| Trung Quốc · AI Agent | `topic:deepseek` | hệ sinh thái DeepSeek |
| Trung Quốc · AI Agent | `topic:qwen` | hệ sinh thái Qwen |
| Trung Quốc · Video AI | `短视频` | video ngắn |
| Trung Quốc · Video AI | `数字人` | người ảo (digital human) |
| Trung Quốc · Marketing | `抖音` | Douyin |
| Trung Quốc · Marketing | `小红书` | Xiaohongshu |
| Trung Quốc · Công cụ làm việc | `飞书` | Feishu / Lark |

## Việc

- [ ] Test đỏ: `features/rising/tests/test_watch_seed_china.py` (10 dòng đúng thứ tự và thông số; chạy lại không
      trùng; truy vấn đã có thì giữ nguyên; vị trí nối sau số lớn nhất). Nới `test_watch_seed.py` thành "16 dòng đầu".
- [ ] `features/rising/migrations/0006_seed_china_watch_queries.py`.
- [ ] Sổ sách: `FEATURE_MAP.md` (F-004 phần tìm; lộ trình F-013/F-014/F-015 thay F-007), `docs/ARCHITECTURE.md`
      (QĐ-24: luật là nguồn phân loại / lọc / gợi ý chính; sửa QĐ-22 — ứng viên đến từ 26 truy vấn), `TASKS.md`.
- [ ] Kiểm chứng: `uv run poe check`; quét thật từng truy vấn mới bằng `manage.py scan` trên **bản sao** CSDL, ghi số
      lượt gọi, số repo lấy được, số repo mới so với kho; đọc tay 20 repo mới.
- [ ] PR, CI xanh, squash-merge; dừng app → sao lưu → `migrate` CSDL thật; lượt hằng ngày kế tiếp chạy 26 truy vấn.
