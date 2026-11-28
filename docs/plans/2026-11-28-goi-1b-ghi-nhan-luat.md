# Gói 1b — Ghi nhãn do luật gắn, chạy cho cả kho trong lượt hằng ngày (F-013): kế hoạch thực thi

> **Cho agent thực thi:** dùng superpowers:executing-plans. Bước dùng ô tick (`- [ ]`).

**Mục tiêu:** repo chưa có nhãn được luật từ khoá (gói 1a) gắn nhãn ngay cả khi không có AI; biết nhãn nào do luật,
nhãn nào do AI; nhãn AI không bao giờ bị luật ghi đè.

**Thiết kế:** `docs/designs/2026-11-28-f013-f015-bo-luat.md`, mục "Gói 1a / 1b".

## Ràng buộc

- Nhánh `feat/f013-ghi-nhan-luat`. TDD. Một migration thêm cột (không RunPython).
- `RepoClassification` thêm `source` (`"ai"` mặc định | `"rule"`) và `rules_version` (0 với dòng AI).
- Dòng do luật ghi: `model="luật"`, `prompt_version=0`, `taxonomy_version` hiện hành, `rules_version` = `version` của
  `keywords.toml`, `reason` bắt đầu bằng "Luật: " (tooltip nhãn nhờ đó ghi rõ nguồn).
- Luật chỉ xét: repo chưa có dòng phân loại, hoặc dòng nguồn luật mà `rules_version` cũ / repo vừa được quét lại.
  Luật không xếp được → **không ghi dòng**; dòng nguồn luật nay không còn khớp → xoá dòng và nhãn. Dòng nguồn luật
  không đổi gì thì chỉ ghi `checked_at`, không viết lại.
- Luật không đụng dòng nguồn AI, `ClassifyMiss`, `ClassifyRun`. AI ghi lên dòng của luật thì dòng thành nguồn AI.
- Bộ chọn của AI (`repositories_needing_labels`) giữ nguyên: repo luật đã xếp coi như xong (AI chỉ còn lo repo luật
  không xếp được); `--reclassify` thì AI làm lại cả dòng của luật (vì `prompt_version=0`).
- Lượt hằng ngày: bước "Phân loại repo" gọi luật cho **cả kho** trước chỗ kiểm `llm_configured()`.
- Lệnh `manage.py classify --rules` (không cần khoá AI). `--compare-rules` chỉ so với dòng nguồn AI.

## Việc

- [ ] Test đỏ: `taxonomy/tests/test_rule_labelling.py`, `test_commands.py` (`--rules`),
      `rising/tests/test_classify_step.py` (luật chạy khi không có AI, cho cả kho).
- [ ] Migration + `services.classify_catalog_by_rules`, sửa `_save`, `compare_rules_with_ai`; `_runner._classify`;
      lệnh; chú thích template.
- [ ] Sổ sách: FEATURE_MAP (F-013 chạy thật), TASKS.
- [ ] Kiểm chứng: `uv run poe check`; trên bản sao CSDL có 6.197 repo tiếng Trung chưa nhãn: chạy `classify --rules`,
      đếm, đọc tay 30 repo; chạy lần hai phải không ghi lại gì; nhãn AI không đổi.
- [ ] PR, CI, gộp; dừng app → sao lưu → migrate CSDL thật → `classify --rules`.
