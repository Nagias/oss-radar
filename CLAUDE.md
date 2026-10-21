# CLAUDE.md — OSS Radar

Đọc file này trước mọi việc. Bản đồ tài liệu:
- `FEATURE_MAP.md` — tính năng nào nằm ở đâu, lối vào, test, nợ liên quan.
- `docs/ARCHITECTURE.md` — vì sao chọn công nghệ/cấu trúc này (bảng quyết định QĐ-xx).
- `DEBT.md` — sổ nợ có chủ đích. Nợ không có trong sổ thì không được tồn tại.
- `TASKS.md` — checklist việc đang làm.

## 1. Mục đích (nguyên văn ý của chủ dự án — không sửa)

> 01 tool chạy ngay trên web ở dạng local giúp crawl được các mã nguồn mở chất lượng và tiềm năng để phát triển. Chất lượng sẽ được đánh giá dựa trên các tiêu chí (có thể mở rộng thêm) như có nhiều star, được nhiều người contributor, có đội ngũ phát triển đứng sau là công ty, doanh nghiệp, tổ chức nghiên cứu... là các tổ chức uy tín. Đặc biệt là nghiên cứu nhiều hơn các repo đến từ Trung Quốc. Còn tiềm năng phát triển thì dựa vào tốc độ phát triển star nhanh trong thời gian ngắn, star khoảng dưới 1000, hoặc liên quan đến dự án, chuyên môn, chuyên ngành của user, có tính ứng dụng cao. Các repository tập trung nhiều vào xây dựng phát triển và hỗ trợ cho AI Agent, hỗ trợ cho ngành marketing, làm video AI, workflow làm video, ảnh AI; vibe code, xây dựng doanh nghiệp 1 người... (hoặc còn nữa). Tuy nhiên sau 1 khoảng thời gian tìm kiếm repo thì tôi thấy AI bị hạn chế ở 01 thứ là search theo keyword, mà cũng không rõ search kiểu gì toàn ra repo chất lượng cực thấp, lại còn không liên quan. Vì thế tool này sẽ giúp quét sâu, quét toàn bộ để đảm bảo yếu tố không bỏ sót, không trùng lặp, có sort by star và recommend repo phù hợp nhất nhu cầu của người dùng. Tool này cũng quét daily và báo cho người dùng repo dạng rising star nữa. Có thể sử dụng API Gemini được lấy từ 9router để làm công cụ AI Search, và sử dụng thêm các API khác như exa, tavily, quan trọng là phải tìm đúng, tìm đủ chứ không phải đề xuất toàn rác.

Thước đo thành công: **tìm đúng, tìm đủ, không trùng, không rác** — mọi tính năng phải phục vụ ít nhất một vế.

## 2. Nguyên tắc thiết kế kiểu Dune

Diễn giải của Claude từ thế giới Dune (chưa có nguồn định nghĩa chuẩn — chủ dự án có thể sửa). Mỗi nguyên
tắc phải biến thành luật kiểm được, không để làm khẩu hiệu.

1. **Không dựng cỗ máy thay trí óc con người** (Butlerian Jihad) → AI là công cụ, không phải nguồn sự thật.
   Số liệu (star, contributor, tổ chức, ngày) chỉ lấy từ API chính thức. AI chỉ mở rộng truy vấn, phân loại,
   chấm mức liên quan, tóm tắt — và luôn lưu kèm lý do. Người dùng là người quyết.
2. **Hiểu hệ quả trước khi hành động** (sinh thái học của Liet-Kynes) → mọi quyết định/đề xuất ghi rõ được gì,
   tốn gì (thời gian, quota, tiền, dung lượng), rủi ro gì. Không chọn theo mốt.
3. **Kỷ luật nước của Fremen** → hạn mức API là nước: không gọi lại thứ đã có, mỗi lần quét có ngân sách gọi
   API và ghi lại đã tiêu bao nhiêu.
4. **Bước đi không theo nhịp để không gọi sâu cát** → tôn trọng giới hạn dịch vụ: giãn nhịp, lùi lại khi bị
   giới hạn, không dội request làm khoá token.
5. **Mỗi sietch tự cung tự cấp** → mỗi tính năng là một thư mục tự đủ (model, service, view, template, test).
   Giao tiếp với tính năng khác chỉ qua `services.py` của nó.
6. **Mentat tính bằng dữ kiện và trình bày lý lẽ** → mọi điểm số, mọi đề xuất phải giải thích được từng thành
   phần. Không có hộp đen.
7. **Đối diện nỗi sợ, đừng trốn nó** (Litany Against Fear) → lỗi phải hiện ra: lần quét lỗi ghi trạng thái
   `failed` kèm lý do; cấm nuốt lỗi (`except: pass`).
8. **Spice phải chảy** → luồng quét hằng ngày phải bền: một nguồn hỏng không làm sập cả lượt; luôn lưu trạng
   thái để chạy tiếp hoặc chạy bù.

## 3. Một loại việc — một đường đúng

| Việc | Đường đúng duy nhất | Mẫu để copy |
|---|---|---|
| Thêm tính năng | thư mục `features/<tên>/` theo cấu trúc F-001 + mục mới trong `FEATURE_MAP.md` (cùng PR) | `features/discovery/` |
| Nghiệp vụ | hàm trong `features/<tên>/services.py` | `features/discovery/services.py` |
| Trang web | function-based view mỏng + `templates/<tên>/` + `urls.py` có `app_name` | `features/discovery/views.py` |
| Kiểm tra dữ liệu nhập | Django Form (dùng chung cho web và dòng lệnh) | `features/discovery/forms.py` |
| Lệnh dòng lệnh / để agent tự kiểm chứng | management command gọi service | `features/discovery/management/commands/scan.py` |
| Ghi bảng `Repository` | chỉ qua `features/catalog/services.py` | `upsert_repositories` |
| Gọi dịch vụ ngoài | client httpx trong `integrations/<dịch vụ>/`, trả dataclass | `integrations/github/client.py` |
| Cấu hình, bí mật | `.env` → `config/settings.py` → `django.conf.settings` | `config/settings.py` |
| Đổi cấu trúc CSDL | sửa `models.py` → `uv run python manage.py makemigrations` | — |
| Ghi log | `logger = logging.getLogger(__name__)` | `features/discovery/services.py` |
| Test có gọi API ngoài | fixture `http_mock` (respx) + JSON phản hồi thật trong `tests/fixtures/` | `integrations/github/tests/` |
| Thêm thư viện | ghi QĐ mới trong `docs/ARCHITECTURE.md` → `uv add <gói>` (phải hỏi chủ dự án) | — |
| Đi đường tắt | ghi `DEBT.md` + đánh dấu `DEBT(D-xxx)` trong code | `DEBT.md` |
| Việc nền, lịch hằng ngày | chưa có đường — làm theo QĐ-11 khi tới tính năng Quét sâu | — |
| Gọi AI | chưa có đường — `integrations/llm/` theo QĐ-12 | — |

Gặp loại việc chưa có trong bảng: dừng, đề xuất đường đi + ghi QĐ trong `docs/ARCHITECTURE.md`, rồi mới làm.

## 4. Đường cấm

| Cấm | Vì sao | Ai chặn |
|---|---|---|
| `import httpx` / `requests` / `urllib.request` ngoài `integrations/` | một cửa ra ngoài | ruff `TID251` |
| Đọc `os.environ` / `os.getenv` ngoài `config/settings.py` | một chỗ cấu hình | ruff `TID251` |
| `print()` trong code ứng dụng | dùng logging hoặc `self.stdout` | ruff `T20` |
| Comment `TODO` / `FIXME` / `HACK` / `XXX` | đường tắt phải vào sổ nợ | ruff `FIX` + test `tests/test_guards.py` |
| Nuốt lỗi (`except: pass`, `except Exception` không raise lại) | nguyên tắc 7 | ruff `S110`, `BLE` |
| Logic nghiệp vụ trong view, template, command | nghiệp vụ chỉ ở services | review |
| Class-based view, Django signals, raw SQL | giấu luồng chạy, agent dễ đọc sai | review |
| Sửa tay migration đã merge | làm hỏng CSDL đang dùng | settings.json hỏi + review |
| Sửa tay `uv.lock` | chỉ uv được ghi | settings.json chặn |
| Test gọi mạng thật (trừ marker `live`) | test phải ổn định, không tốn quota | fixture `http_mock` tự động |
| AI sinh ra số liệu (star, contributor, tổ chức…) | nguyên tắc 1 | review + test khi có AI |
| Commit/push thẳng `main`, force-push, `--no-verify` | mất lưới an toàn | branch protection + settings.json chặn |
| Ghi token/mật khẩu vào code, settings.json, log, chat | lộ khoá | `.gitignore` + chặn đọc `.env` + review |
| Thêm thư viện không có QĐ | phình phụ thuộc, tăng bề mặt lỗi | settings.json hỏi `uv add` |
| Gọi API trong vòng lặp không giới hạn | khoá token, cháy quota | review (sau có ngân sách quét) |

## 5. Lệnh

Chạy trong PowerShell tại thư mục gốc dự án (đường dẫn có dấu cách → luôn đặt trong ngoặc kép).

```
uv sync                                         # cài đúng phiên bản trong uv.lock
copy .env.example .env                          # rồi điền GITHUB_TOKEN (chủ dự án tự điền)
uv run python manage.py migrate                 # tạo/cập nhật CSDL trong data/
uv run poe dev                                  # chạy web tại http://127.0.0.1:8765
uv run poe check                                # TOÀN BỘ cổng kiểm tra — đúng như CI
uv run poe fmt                                  # tự sửa định dạng + lỗi lint sửa được
uv run poe test                                 # chỉ chạy test (có đo độ phủ)
uv run poe test-live                            # test gọi GitHub thật (cần GITHUB_TOKEN)
uv run python manage.py scan "topic:ai-agent"   # chạy thật luồng F-001 từ dòng lệnh
```

## 6. Nhánh, PR và tự kiểm chứng

- Không làm việc trên `main`. Tên nhánh: `feat/fNNN-<slug>`, `fix/<slug>`, `chore/<slug>`, `docs/<slug>`.
- Một PR = một tính năng hoặc một sửa lỗi. Cùng PR phải cập nhật: `FEATURE_MAP.md`; `DEBT.md` nếu có đường
  tắt; `docs/ARCHITECTURE.md` nếu có quyết định mới.
- Viết test đỏ trước cho hành vi mới (TDD), rồi mới viết code cho xanh.
- **Chưa được báo "xong" khi chưa:**
  1. `uv run poe check` xanh;
  2. chạy thật luồng vừa làm (lệnh `manage.py` hoặc mở trình duyệt) và ghi kết quả vào mô tả PR;
  3. chạy `uv run poe test-live` nếu đã đụng tới phần gọi GitHub;
  4. ghi rõ trong PR: làm gì, để được gì, kiểm chứng thế nào, phần nào chưa kiểm.
- Merge chỉ khi CI xanh; chỉ squash-merge.
- Commit message tiếng Việt có dấu, dạng `<loại>: <mô tả>`; loại ∈ `feat`, `fix`, `test`, `docs`, `chore`,
  `refactor`. Ví dụ: `feat: quét GitHub theo truy vấn và lưu không trùng`.

## 7. Nợ có chủ đích

- Đường tắt nào cũng phải có mục trong `DEBT.md` (mã `D-NNN`): nợ gì, vì sao chấp nhận, khi nào trả, rủi ro.
- Chỗ trong code liên quan ghi comment `# DEBT(D-NNN): <một dòng>`. `tests/test_guards.py` bắt lỗi nếu mã nợ
  trong code không có trong sổ hoặc đã ghi "Đã trả".
- Trả nợ = xoá dấu `DEBT(...)` trong code + chuyển trạng thái trong sổ, trong cùng PR.

## 8. Quy ước code

- Tên biến, hàm, lớp, file: tiếng Anh. Giao diện, docstring, comment, tài liệu, commit: tiếng Việt có dấu.
- Mọi hàm có khai báo kiểu (mypy strict). Mọi thời điểm dùng `django.utils.timezone.now()` (có múi giờ).
- Dữ liệu từ dịch vụ ngoài là dữ liệu không tin cậy: kiểm tra kiểu khi parse, template tự escape, link ngoài
  có `rel="noopener noreferrer"`.
- Comment chỉ viết khi giúp người sau hiểu "vì sao"; không kể lể "đang làm gì".

## 9. Bảo mật

- Bí mật chỉ nằm trong `.env` (đã gitignore). Không đọc, không in nội dung `.env` ra chat hay log.
- Luật chặn đọc `.env` trong `.claude/settings.json` chỉ chống lộ **vô tình**, không phải hàng rào thật:
  agent được sửa code và tự chạy test thì về lý thuyết đọc được mọi file. Vì vậy mọi token đặt vào `.env`
  phải ở mức quyền thấp nhất có thể (lộ ra cũng ít hại), và không đặt bí mật quan trọng nào trong dự án.
- App chỉ nghe `127.0.0.1`. Muốn mở ra mạng LAN/Internet phải trả nợ D-001 trước.
- Token GitHub dùng loại fine-grained, chỉ quyền đọc public.
