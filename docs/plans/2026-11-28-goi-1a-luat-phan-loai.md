# Gói 1a — Bộ từ khoá, hàm luật B và C, lệnh so sánh với nhãn AI (F-013): kế hoạch thực thi

> **Cho agent thực thi:** dùng superpowers:executing-plans. Bước dùng ô tick (`- [ ]`).

**Mục tiêu:** có hàm thuần gắn nhãn "Làm được gì" và "Dành cho ai" cho một repo chỉ bằng từ khoá, và một lệnh chỉ đọc
đo hàm đó so với ~40.000 nhãn AI đang có. Gói này **chưa ghi nhãn nào** vào CSDL (việc của gói 1b).

**Thiết kế:** `docs/designs/2026-11-28-f013-f015-bo-luat.md`, mục "Luật B", "Luật C", "Gói 1a / 1b".

## Ràng buộc

- Nhánh `feat/f013-luat-phan-loai`. TDD. Không migration, không thêm thư viện, không đụng `categories.toml`.
- Từ khoá ở `features/taxonomy/keywords.toml` (`version` riêng), đọc và kiểm bằng `features/taxonomy/keywords.py`;
  file hỏng → `manage.py check` báo `taxonomy.E002`.
- Hàm luật ở `features/taxonomy/rules.py`, thuần (không CSDL, không mạng):
  - từ khoá mạnh 2 điểm, yếu 1 điểm; nhóm "Làm được gì" cần ≥ 2 điểm; tối đa 3 nhóm, điểm cao trước;
  - không nhóm nào đủ điểm → `None` (không ép vào "Khác");
  - "Dành cho ai": +2 khi suy được từ nhóm "Làm được gì" đã chọn (Game → Làm game +3), cộng điểm từ khoá riêng; cần
    ≥ 3 điểm (Lập trình viên ≥ 2); tối đa 2 nhãn; không đủ thì để trống;
  - khớp theo **nguyên từ** trên topic, tên repo và mô tả (chữ thường; `text-to-video` khớp cả "text to video");
    từ khoá chữ Hán khớp theo chuỗi con; `reason` liệt kê từ khoá đã khớp, cắt theo `MAX_REASON`.
- Lệnh `manage.py classify --compare-rules`: chỉ đọc, in bảng từng nhóm (AI gắn / luật gắn / bắt được / đúng) và số
  repo luật không xếp được.

## Mục tiêu đo (so với nhãn AI)

- "Làm được gì": Agent, Công cụ lập trình, Video, Ảnh, Hạ tầng AI đúng ≥ 80% và bắt được ≥ 80%; nhóm nhỏ ≥ 70%.
- "Dành cho ai": Lập trình viên, Làm game đúng ≥ 85%; bốn nhóm còn lại đúng ≥ 75% (ưu tiên đúng hơn đủ).
- Nhóm không đạt thì ghi rõ trong PR, không giấu.

## Việc

- [ ] Test đỏ: `tests/test_keywords.py` (file thật đọc được, mã lạ / từ khoá trùng / thiếu nhóm → lỗi, check E002),
      `tests/test_rules.py` (khớp nguyên từ, chữ Hán, điểm, trần 3 / 2, `None`, suy "Dành cho ai", `reason`).
- [ ] `keywords.py`, `keywords.toml`, `rules.py`, `checks.py` (E002).
- [ ] `services.compare_rules_with_ai()` + cờ `--compare-rules` của lệnh `classify` (test lệnh).
- [ ] Chỉnh từ khoá theo số đo trên bản sao CSDL thật tới khi đạt mục tiêu hoặc hết cách.
- [ ] Sổ sách: FEATURE_MAP (F-013 phần 1a), TASKS.
- [ ] Kiểm chứng: `uv run poe check`; bảng so sánh trên bản sao; đọc tay 50 repo ngẫu nhiên; PR, CI, gộp.
