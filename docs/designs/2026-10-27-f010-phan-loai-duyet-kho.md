# F-010 — Phân loại repo theo nhóm bằng AI, trang duyệt kho có lọc và sắp xếp: bản thiết kế

> **Trạng thái: ĐÃ DUYỆT** (soạn 2026-10-27 sau buổi hỏi đáp; chủ dự án đồng ý làm và đã điền `LLM_API_KEY`).
> Đo thật 9router (2026-10-27): gọi được `ag/gemini-3.8-flash-low`; mặc định trả dạng luồng nên phải gửi
> `stream: false`; nội dung bọc khung ```json``` dù có `response_format`; mỗi lượt có ~2.000 token nền (3 repo: 2.285 vào,
> 137 ra, 6,4 giây).
> Chỗ ghi "(quyết định của Claude)" là đề xuất, bác được. Đã qua một lượt đọc thử với vai người làm theo
> (mục 15).

## 1. Vì sao làm

Chủ dự án làm Digital Marketing, tự vibe code tool MMO (chỉnh sửa video, làm YouTube) và game. Dùng thử app
(F-002, F-005, F-006) thấy cơ chế tốt nhưng **mọi repo bị trộn vào một danh sách, không lọc, không sắp được**:
mỗi sáng vài chục tới vài nghìn repo, không có thời gian đọc hết nên không biết tập trung vào đâu.

App phải phục vụ 3 việc của chủ dự án (nguyên văn ý):
1. hỗ trợ các dự án đang làm;
2. phát hiện repo tiềm năng để clone / pull về làm nền;
3. cập nhật công nghệ mới dùng được.

**Thành công:** mở app, bấm chọn nhóm (ví dụ "Nhà sáng tạo nội dung" + "Video & làm phim AI"), thấy ngay danh
sách ngắn đúng nhóm đó, sắp theo star / rising / số tăng. Lướt vài phút là chọn được repo đáng xem.

## 2. Chủ dự án đã chốt (2026-10-27)

- **AI chỉ phân loại**, dựa vào mô tả và từ khoá của repo. **AI không đánh giá, không chấm điểm, không gợi ý.**
- **Xếp hạng giữ như hiện tại** (số liệu chính thức từ GitHub): rising star, star, số tăng, điểm F-006.
- **Bộ nhóm hai lớp** do Claude đề xuất, chủ dự án đồng ý không sửa (mục 4).
- AI dùng Gemini qua 9router (QĐ-12).
- Duyệt thiết kế một lần, rồi Claude tự làm, tự test; **không xoá file hay thư mục nào ngoài dự án**.

## 3. Mục tiêu, không làm, phản mục tiêu

**Mục tiêu**
1. Mỗi repo trong kho được gắn nhãn hai lớp (mục 4) bằng Gemini; lưu lại, không gọi lại khi repo không đổi.
2. **Trang mới "Kho repo" (`/repos/`)**: duyệt toàn kho, lọc theo nhóm, sắp theo nhiều cách, phân trang. Trả
   nợ D-007 (trang lần quét chỉ hiện 500 repo).
3. Trang Rising star và trang lần quét có thêm nhãn nhóm và ô lọc theo nhóm.
4. Có ngân sách lượt gọi AI, ghi lại đã tiêu bao nhiêu (nguyên tắc 3).

**Không làm trong F-010**
- AI chấm mức liên quan / gợi ý theo nhu cầu (F-007 cũ) — chủ dự án nói không cần đánh giá.
- Số contributor, số pull request, "tổ chức uy tín" (F-003): app chưa thu các số này. Trang Kho repo chừa chỗ để
  thêm cách sắp "nhiều contributor" khi F-003 xong.
- Thông báo ra ngoài app (F-009), Exa/Tavily (F-008), ưu tiên repo Trung Quốc (F-004).
- Trang sửa danh sách nhóm trên web (sửa bằng file cấu hình, mục 6).

**Phản mục tiêu** (chạy được mà vẫn coi là hỏng)
- AI tạo ra hay sửa số liệu (star, fork, ngày…) — nguyên tắc 1.
- Repo chưa phân loại hoặc phân loại sai **biến mất** khỏi trang: luôn có lối xem "Chưa phân loại" và lọc
  "Tất cả".
- Phân loại hỏng (9router tắt, hết lượt, sai khoá) làm hỏng lượt hằng ngày hoặc mất báo cáo (bài học F-006).
- Gọi AI lại cho repo đã phân loại mà mô tả không đổi; gọi vượt ngân sách.
- Trang Kho repo chậm tới mức khó dùng (> 2 giây với 32.000 repo).

## 4. Bộ nhóm (taxonomy)

Mỗi nhóm có mã (slug, không đổi) và tên hiển thị. Mỗi repo: **1–2 nhãn lớp "Dành cho ai"**, **1–3 nhãn lớp
"Làm được gì"**. AI không chắc thì gắn `khac` ("Khác") ở lớp "Làm được gì" và để trống lớp "Dành cho ai".

**Lớp 1 — Dành cho ai**

| Mã | Tên |
|---|---|
| `developer` | Lập trình viên |
| `marketer` | Marketer |
| `business` | Kinh doanh & doanh nghiệp một người |
| `creator` | Nhà sáng tạo nội dung (video, YouTube, ảnh) |
| `gamedev` | Làm game |
| `research` | Nghiên cứu & dữ liệu |

**Lớp 2 — Làm được gì**

| Mã | Tên |
|---|---|
| `agent` | AI Agent & tự động hoá |
| `video` | Video & làm phim AI |
| `image` | Ảnh & thiết kế AI |
| `audio` | Âm thanh & giọng nói |
| `writing` | Viết nội dung & SEO |
| `social` | Mạng xã hội & YouTube |
| `ads` | Quảng cáo & phân tích marketing |
| `scraping` | Thu thập dữ liệu (crawl, scrape) |
| `devtools` | Công cụ lập trình & vibe code (IDE, CLI, MCP) |
| `ai_infra` | Mô hình & hạ tầng AI (chạy LLM, RAG, fine-tune) |
| `webapp` | Web, app & giao diện |
| `game` | Game engine & tài nguyên game |
| `commerce` | Bán hàng & thương mại điện tử |
| `productivity` | Năng suất & quy trình (workflow, no-code) |
| `khac` | Khác |

Mỗi nhóm kèm 1–2 câu mô tả cho AI (cái gì thuộc nhóm, cái gì không) trong file cấu hình — người làm soạn.

## 5. Cách phân loại

- **Đầu vào cho AI** mỗi repo: `full_name`, mô tả, topics, ngôn ngữ chính. Không gửi README (tốn token, không
  cần cho phân loại theo mô tả — chủ dự án chốt "dựa vào keyword mô tả").
- **Gom lô**: tối đa 40 repo mỗi lượt gọi (quyết định của Claude). Ước lượng đo trên kho thật (32.412 repo, mô tả
  trung bình 127 ký tự): ~3.400 token vào + ~1.000 token ra mỗi lượt; cả kho ~810 lượt, ~3,6 triệu token.
- **Đầu ra AI**: JSON, mỗi repo `{id, audience: [mã…], aspects: [mã…], reason: "≤ 15 từ"}`. `reason` là vài từ
  khoá khiến AI xếp như vậy (nguyên tắc 6: không hộp đen) — **không phải lời đánh giá**.
- **Kiểm đầu ra (dữ liệu AI là không tin cậy):** chỉ nhận mã có trong bộ nhóm; cắt bớt quá số nhãn cho phép;
  repo nào thiếu trong câu trả lời, hoặc JSON hỏng → coi như chưa phân loại, lượt sau thử lại; không bao giờ
  ghi số liệu nào khác từ AI. Mô tả repo là văn bản từ người lạ (có thể chứa câu "bỏ qua hướng dẫn…"): AI
  không có công cụ nào để gọi, đầu ra chỉ là nhãn trong danh sách cố định nên lệnh chèn không gây hại được.
- **Lưu**: mỗi repo một bản ghi phân loại gồm nhãn, lý do, model, phiên bản prompt, phiên bản bộ nhóm, dấu vân
  tay đầu vào (băm của mô tả + topics), thời điểm.
- **Phân loại lại** chỉ khi: dấu vân tay đổi (mô tả / topics đổi), hoặc phiên bản bộ nhóm / prompt đổi và người
  dùng chạy lệnh phân loại lại. Không tự phân loại lại cả kho khi đổi bộ nhóm (tốn ~810 lượt).
- **Thứ tự ưu tiên** khi ngân sách không đủ: rising star của lượt gần nhất → ứng viên của lượt → repo nhiều star
  trước.
- Nhãn `khac` chỉ dùng khi không có nhãn "Làm được gì" nào khác (quyết định của Claude).

## 6. Bộ nhóm nằm ở đâu

File cấu hình trong dự án (ví dụ `features/taxonomy/categories.toml`), sửa bằng tay được, không cần migration
(quyết định của Claude). Có `version`; đổi file thì tăng `version`. Nhãn cũ có mã không còn trong file thì bị
bỏ qua khi hiển thị. Kiểm file khi app khởi động (`manage.py check`): mã trùng, thiếu tên, lớp sai → báo lỗi rõ.

## 7. Chạy lúc nào, tốn bao nhiêu

- **Bước mới trong lượt hằng ngày** (quyết định của Claude sau lượt đọc thử): "Phân loại repo" sau bước lấy hồ
  sơ chủ, trước lập báo cáo, **chỉ cho rising star và ứng viên của lượt** (vài chục repo, 1–3 lượt gọi, vài
  chục giây) — để báo cáo buổi sáng không ra muộn. Như bước hồ sơ chủ: hỏng gì (9router tắt, 401, hết lượt,
  bấm Dừng) cũng **chỉ ghi chú rồi đi tiếp lập báo cáo**.
- **Phân loại dần phần còn lại của kho**: một việc định kỳ riêng trong `settings.SCHEDULED_JOBS` (QĐ-15), chỉ
  chạy khi lượt hằng ngày hôm nay đã xong và luồng nền rảnh; ngân sách **150 lượt gọi AI/ngày** (~6.000 repo;
  chỉnh trong cấu hình). Rẻ khi chưa đến lượt (một câu truy vấn). Bấm Dừng / tắt app thì lần sau làm tiếp.
- **Nhịp gọi mặc định an toàn** (khi chưa biết hạn mức của 9router): tối đa **10 lượt/phút**, gặp 429 thì chờ theo
  `Retry-After` (hoặc 60 giây) rồi gọi lại tối đa 3 lần; quá thì dừng việc phân loại, để lần sau. Con số nằm
  trong cấu hình, chỉnh theo câu trả lời của chủ dự án ở mục 13.
- **Lệnh `manage.py classify --budget N`** để phân loại bù cả kho lần đầu và để chạy lại sau khi đổi bộ nhóm
  (`--reclassify`). In tiến độ, tôn trọng Ctrl+C, lưu từng lô ngay sau khi gọi. Từ chối chạy khi luồng nền của
  app đang phân loại (khoá chéo như lần quét). Ở nhịp 10 lượt/phút, cả kho (~810 lượt) mất ~1,5 giờ.
- **Giãn nhịp, gọi lại, ngân sách** nằm trong client `integrations/llm/` như client GitHub: lỗi tạm thời (5xx, mất
  mạng, 429) gọi lại có giãn nhịp, tối đa 3 lần; lượt gọi đã tiêu luôn được ghi.
- **Tiền:** đi qua 9router của chủ dự án (model Gemini Flash mức thấp, tên model trong `.env`). Chi phí thật tuỳ gói
  9router; app ghi số token vào/ra của mỗi lượt để chủ dự án tự đối chiếu.

## 8. Người dùng thấy gì

**Trang mới "Kho repo" `/repos/`** (thêm vào thanh điều hướng)
- Ô lọc:
  - Dành cho ai (chọn nhiều)
  - Làm được gì (chọn nhiều)
  - từ khoá trong tên / mô tả
  - ngôn ngữ
  - star tối thiểu / tối đa
  - tạo trong N ngày
  - chỉ rising star của báo cáo mới nhất
  - hiện cả repo "Nghi cao" (mặc định ẩn, như F-006)
  - **giấy phép cho phép dùng thương mại** (MIT, Apache-2.0, BSD, ISC… — danh sách trong cấu hình; quyết định của
    Claude: giúp chủ dự án tránh clone repo GPL/AGPL/không giấy phép để bán)
  - "Chưa phân loại"
- Chọn nhiều trong cùng một lớp là **HOẶC**; giữa hai lớp là **VÀ** (quyết định của Claude). Ví dụ: (Marketer
  hoặc Nhà sáng tạo) và (Video).
- Sắp theo:
  - star
  - fork
  - star tăng 7 ngày (từ lần xét rising gần nhất — repo chưa từng xét nằm cuối)
  - mới tạo
  - đẩy code gần nhất
  - **Chất lượng** (F-006)
- Phân trang 50 repo/trang, có tổng số kết quả. Mỗi dòng gồm:
  - tên (link GitHub), mô tả, nhãn nhóm (bấm vào nhãn = lọc theo nhãn đó), lý do phân loại khi di chuột;
  - star, fork, tăng 7 ngày, điểm Chất lượng, nhãn Cần xem / Nghi cao, ngôn ngữ, ngày đẩy code.
- Đầu trang: số repo theo từng nhóm (bao nhiêu repo "Video & làm phim AI"…), bấm vào là lọc.
- Đọc từ CSDL, không gọi API.

**Trang Rising star** — mỗi dòng có nhãn nhóm; thêm hai ô lọc "Dành cho ai", "Làm được gì".

**Trang lần quét** — mỗi dòng có nhãn nhóm. Bảng bỏ giới hạn 500 bằng cách dẫn sang Kho repo đã lọc theo lần quét
đó (`/repos/?scan=<id>`) — trả D-007.

**Trang Theo dõi** — ước lượng lượt gọi mỗi ngày có thêm lượt gọi AI; lịch sử lượt có cột "Lượt gọi AI".

## 9. Sắp theo Chất lượng trên 32.000 repo

Điểm F-006 tính lúc xem, không lưu (QĐ-17). Sắp cả kho theo điểm, và **ẩn repo "Nghi cao" trên cả kho**, phải
tính cho mọi repo đang lọc. Đo: hàm thuần, ~32.000 repo. Nếu đo thật thấy > 1 giây thì **lưu điểm Chất lượng và
điểm nghi star giả vào cột**, tính lại khi repo được ghi vào kho, khi lấy hồ sơ chủ, và bằng lệnh khi đổi công
thức. Để người làm đo rồi chọn, ghi QĐ mới nếu đổi QĐ-17.

## 10. Bố cục mã

| Phần | Vị trí |
|---|---|
| Client AI (OpenAI-compatible, httpx, giãn nhịp, ngân sách, lỗi có tên) | `integrations/llm/` (QĐ-12 → thành QĐ-18 khi làm) |
| Cấu hình | `.env`: `LLM_BASE_URL` (mặc định `http://localhost:20128/v1`), `LLM_API_KEY`, `LLM_MODEL` (mặc định `ag/gemini-3.8-flash-low`) → `config/settings.py` |
| Bộ nhóm, prompt, kiểm đầu ra, lưu nhãn | tính năng mới `features/taxonomy/` |
| Trang Kho repo | tính năng mới `features/browse/` (lọc theo lần quét, rising star, tăng 7 ngày phải đọc `discovery` và `rising`; đặt trong `catalog` sẽ tạo vòng phụ thuộc) |
| Bước phân loại trong lượt hằng ngày | `features/rising/services.py` gọi `taxonomy.services` (D-009 nói file này đã dài — xem mục 12) |

Chiều phụ thuộc: `rising` → `taxonomy` → `catalog`; `browse` → `taxonomy`, `scoring`, `catalog`, `rising`,
`discovery` (chỉ qua `services.py`). `taxonomy` không import `rising`/`discovery`; không tính năng nào import
`browse`.

## 11. Kiểm chứng

- **Test** (không gọi mạng; 9router giả bằng respx, phản hồi mẫu lấy từ một lượt gọi thật đã lưu):
  - client AI: thành công, 401, 429, 5xx, JSON hỏng, ngân sách;
  - kiểm đầu ra AI: mã lạ, quá nhãn, thiếu repo, câu chèn lệnh trong mô tả;
  - không gọi lại repo không đổi;
  - lượt hằng ngày: phân loại hỏng vẫn có báo cáo;
  - trang Kho repo: từng ô lọc, HOẶC/VÀ, sắp, phân trang, ẩn Nghi cao, Chưa phân loại;
  - số câu truy vấn của trang không tăng theo số dòng.
- **Test gọi thật** (`poe test-live`): 1 lượt phân loại 3 repo thật qua 9router.
- **Chạy thật**: phân loại cả kho bằng lệnh `classify`, ghi số lượt / token / thời gian; mở `/repos/` lọc "Nhà sáng
  tạo nội dung + Video", đo thời gian tải trang; kiểm tay 30 repo ngẫu nhiên xem nhãn có hợp lý, ghi tỉ lệ sai vào PR.

## 12. Rủi ro

- **Nhãn sai**: AI chỉ dựa vào mô tả ngắn, repo mô tả mơ hồ sẽ bị xếp sai hoặc vào "Khác". Giảm bằng: lý do
  hiện kèm nhãn; luôn lọc được "Tất cả"; kiểm tay 30 repo khi chạy thật.
- **9router hoặc gói Gemini đổi / hết hạn mức**: phân loại dừng, phần còn lại của app chạy bình thường.
- **`rising/services.py` dài thêm** (nợ D-009): bước mới chỉ là lời gọi sang `taxonomy`; tách file vẫn để ở PR
  trả D-009.
- **Đổi bộ nhóm** thì nhãn cũ lệch tới khi chạy `classify --reclassify` (~810 lượt).

## 13. Chủ dự án cần làm / quyết

1. **Điền khoá 9router vào `.env`**: thêm dòng `LLM_API_KEY=<khoá>` (lấy trong trang quản lý của 9router). Không
   có khoá thì Claude vẫn làm và test bằng 9router giả, nhưng không chạy thật được.
2. **Hạn mức của 9router / Gemini** (mỗi phút, mỗi ngày) và khoá có dùng chung với tool khác không. Chưa biết thì
   dùng mặc định an toàn ở mục 7 (10 lượt/phút, kho trải ra theo ngân sách 150 lượt/ngày).
3. Duyệt bản thiết kế này.

## 14. Để người làm tự quyết

Tên trường, bảng, hàm; nội dung prompt (theo mục 5); giao diện cụ thể của ô lọc; chọn vị trí trang Kho repo; cách
lưu điểm Chất lượng nếu đo thấy chậm (mục 9).

## 15. Lượt đọc thử với vai người làm theo (2026-10-27)

Hai câu cần chủ dự án / đã xử lý:
1. Hạn mức 9router chưa biết → mục 7 đặt mặc định an toàn, mục 13 hỏi chủ dự án.
2. Phân loại cả ngân sách trước báo cáo làm báo cáo buổi sáng ra muộn 15–40 phút → Claude chốt: trước báo cáo
   chỉ phân loại repo của lượt; phần kho còn lại là việc định kỳ riêng (mục 7).

Claude tự chốt thêm: trang Kho repo ở `features/browse/` và chiều phụ thuộc (mục 10); ẩn "Nghi cao" trên cả kho
xử lý cùng bài toán tốc độ ở mục 9; `khac` không đi kèm nhãn khác; lọc giấy phép cho phép dùng thương mại.
