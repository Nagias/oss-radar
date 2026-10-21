# FEATURE_MAP — bản đồ tính năng

Bản đồ để người và agent tìm đúng chỗ trong 30 giây: tính năng nào, nằm ở thư mục nào, vào bằng đường nào,
test ở đâu, đang nợ gì.

**Luật cập nhật**
- Thêm/sửa/xoá tính năng → cập nhật file này **trong cùng PR**. PR thiếu cập nhật thì không merge.
- Mỗi thư mục `features/<tên>/` và `integrations/<tên>/` phải có mặt trong file này (dạng `` `features/<tên>/` ``).
  `tests/test_guards.py` kiểm tự động — quên là CI đỏ.
- Mã tính năng `F-NNN` tăng dần, không dùng lại.

## Tổng quan

| Mã | Tính năng | Trạng thái | Thư mục | Lối vào | Test chính | Nợ |
|---|---|---|---|---|---|---|
| — | (chưa có tính năng nào) | — | — | — | — | — |

## Mô-đun lõi và cửa ra ngoài

| Mô-đun | Vai trò | Ai được dùng |
|---|---|---|
| — | (chưa có) | — |

## Chi tiết từng tính năng

<!-- Khuôn cho mỗi tính năng — copy khối dưới, điền đủ các mục:

### F-NNN — <Tên tính năng>
- **Phục vụ vế nào của mục tiêu:** tìm đúng / tìm đủ / không trùng / không rác
- **Người dùng làm gì → thấy gì:** …
- **Luồng chạy:** lối vào → service → (integrations) → model → giao diện
- **Thành phần:** model …; service …; view/URL …; template …; command …
- **Phụ thuộc:** tính năng/mô-đun nào, qua hàm nào
- **Kiểm chứng tự động:** file test + test end-to-end
- **Kiểm chứng tay:** lệnh hoặc thao tác trên trình duyệt
- **Nợ liên quan:** D-xxx
-->

## Lộ trình dự kiến (chưa làm — thứ tự có thể đổi khi duyệt)

| Mã dự kiến | Tính năng | Phục vụ |
|---|---|---|
| F-001 | Quét GitHub theo truy vấn → lưu không trùng → xem sắp theo star (bộ khung) | không trùng, sort by star |
| F-002 | Quét sâu: chia lát truy vấn vượt trần 1.000 kết quả, chạy nền | tìm đủ |
| F-003 | Làm giàu: số contributor, tổ chức đứng sau, xác minh tổ chức, quốc gia | tìm đúng |
| F-004 | Ưu tiên repo Trung Quốc: tín hiệu location, README, danh sách tổ chức | tìm đúng |
| F-005 | Ảnh chụp star hằng ngày + phát hiện rising star + lịch quét hằng ngày | tiềm năng |
| F-006 | Chấm điểm Chất lượng/Tiềm năng có giải thích | không rác |
| F-007 | Hồ sơ nhu cầu người dùng + AI chấm mức liên quan (Gemini qua 9router) | tìm đúng |
| F-008 | Nguồn khám phá phụ Exa, Tavily | tìm đủ |
| F-009 | Thông báo rising star hằng ngày | rising star |
