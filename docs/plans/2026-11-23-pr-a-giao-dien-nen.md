# PR A — Giao diện nền: kế hoạch thực thi

> **Cho agent thực thi:** dùng superpowers:executing-plans (hoặc subagent-driven-development) để làm từng task.
> Bước dùng ô tick (`- [ ]`) để theo dõi.

**Mục tiêu:** dựng hệ giao diện mới kiểu ElevenLabs (nền trắng, chữ và nút đen, thanh bên trái, phông Be Vietnam Pro,
tự tối theo máy) và áp lên mọi trang hiện có, **không đổi hành vi**.

**Kiến trúc:** vẫn render phía máy chủ (QĐ-05). Một file CSS `static/css/app.css` viết lại theo token. Một file JS viết
tay `static/js/app.js` ≤ 150 dòng, chỉ tăng cường dần (tắt JS vẫn dùng đủ). Phông đóng gói trong
`static/fonts/be-vietnam-pro/`. Test bám HTML chuyển sang bộ đọc HTML nhỏ `tests/html.py` để bớt mong manh.

**Công nghệ:** Django 5.2 template, CSS thuần, JS thuần, `html.parser` có sẵn của Python. Không thêm thư viện.

**Thiết kế:** `docs/designs/2026-11-23-f011-f012-kham-pha-trending.md`, mục "PR A".

## Ràng buộc chung

- Nhánh `chore/giao-dien-nen`. Commit tiếng Việt dạng `<loại>: <mô tả>`.
- Không đổi chữ hiển thị, tên ô form, id, `action` của form, thẻ `meta refresh`, URL.
- Giữ các lớp test đang bám: `num`, `desc`, `unverified-list`, `hidden-repos`, `status-*`, `badge-*`, `spark`,
  `<strong>tên</strong>`, `class="error"`.
- 4 mục điều hướng giữ nguyên thứ tự, nhãn, URL: Quét `/`, Rising star `/rising/`, Kho repo `/repos/`,
  Theo dõi `/rising/watch/`. `nav` giữ `aria-label="Các trang chính"`.
- Không tài nguyên nào tải từ mạng: không `http(s)://` trong `src`, `<link href>`, CSS `url()`, `@import`.
- `static/js/app.js` ≤ 150 dòng. Không comment TODO/FIXME/HACK/XXX trong template, CSS, JS.
- Token sáng: nền `#fff`, bề mặt phụ `#fafafa`, chữ `#0a0a0a`, chữ phụ `#525252`, chữ mờ `#a3a3a3`, viền `#e5e5e5`,
  viền đậm `#d4d4d4`, nút chính nền `#000` chữ `#fff`. Tối: nền `#0a0a0a`, bề mặt `#111`, phụ `#171717`, chữ
  `#fafafa`, chữ phụ `#a3a3a3`, viền `#262626`, viền đậm `#404040`, nút chính nền `#fafafa` chữ `#0a0a0a`.
- Bo góc 6 / 10 / 14 / 999. Cỡ chữ gốc 14px. Thứ tự phông `"Be Vietnam Pro", system-ui, "Segoe UI", sans-serif`.

## Điểm dễ hỏng cần kiểm (không có test JS tự động — D-010)

1. Tắt JS: form lọc ở `/rising/` và `/repos/` vẫn lọc được bằng nút "Lọc" → kiểm ở Task 6.
2. Đang gõ ở ô chữ mà form tự gửi theo từng phím → chỉ tự gửi với select/checkbox/number; kiểm ở Task 6.
3. Phím `/` cướp con trỏ khi đang gõ trong ô khác → kiểm ở Task 6.
4. Màn hình 375px: bảng rộng làm cả trang cuộn ngang → `document.documentElement.scrollWidth == innerWidth`, Task 6.
5. Chữ tiếng Việt có dấu hiển thị sai phông (thiếu `unicode-range` vietnamese) → Task 2 có test khai đủ 3 bộ ký tự
   cho 4 độ đậm; Task 6 nhìn bằng mắt.

---

### Task 1: Bộ đọc HTML cho test, chuyển test điều hướng và nút sang dùng nó

**Files:**
- Create: `tests/html.py`, `tests/test_html_helper.py`
- Modify: `features/rising/tests/test_views.py` (dòng ~262, 274, 295, 325, 336, 372 và 3 test điều hướng + `_nav`)

**Interfaces — Produces:**
```python
@dataclass(frozen=True)
class NavLink: href: str; text: str; current: bool          # current = có aria-current="page"
@dataclass(frozen=True)
class Button: text: str; disabled: bool
@dataclass(frozen=True)
class Form: method: str; action: str; attrs: dict[str, str | None]; buttons: tuple[Button, ...]

def nav_links(page: str, label: str = "Các trang chính") -> list[NavLink]   # trong <nav aria-label=label>
def buttons(page: str) -> list[Button]                                        # mọi <button>, theo thứ tự
def forms(page: str) -> list[Form]
```
Chữ lấy bằng nối text con, gộp khoảng trắng, bỏ phần trong phần tử `aria-hidden="true"` và `<svg>`.

- [ ] **Bước 1: test đỏ** `tests/test_html_helper.py`:
  - `test_nav_links_reads_href_text_and_current` — trang có 2 `nav` (một khác `aria-label`), link có lớp và thuộc
    tính thêm, có `<span aria-hidden="true">•</span>` → trả đúng 2 `NavLink` của nav cần tìm, `current` đúng.
  - `test_buttons_reads_text_and_disabled` — `<button class="x" disabled>Chạy ngay</button>` và nút có khoảng
    trắng xuống dòng → `[Button("Chạy ngay", True), Button("Lọc", False)]`.
  - `test_forms_groups_buttons_and_attrs` — 2 form, form một có `data-autosubmit` → `attrs["data-autosubmit"] is None`
    (thuộc tính không giá trị), `buttons` đúng của từng form, `method` mặc định `"get"`.
- [ ] **Bước 2:** `uv run pytest tests/test_html_helper.py -q` → FAIL (chưa có module).
- [ ] **Bước 3:** viết `tests/html.py` bằng `html.parser.HTMLParser`.
- [ ] **Bước 4:** chạy lại → PASS.
- [ ] **Bước 5:** sửa `features/rising/tests/test_views.py` (vẫn chạy trên HTML cũ):
  - 3 test điều hướng dùng `nav_links(page)`; khẳng định giữ nguyên: danh sách `(href, text)` đúng thứ tự 4 mục và
    `[l.text for l in links if l.current] == [current]`; trang từ chối Chạy ngay: mục hiện tại là "Rising star";
    view cùng tên khác namespace: không mục nào `current`. Xoá `_nav`.
  - `">Chạy tiếp</button>" in page` → `Button("Chạy tiếp", False) in buttons(page)`; tương tự "Chạy ngay";
    hai regex `disabled` → `Button("Chạy ngay", True) in buttons(page)` / `Button("Chạy tiếp", True)`.
- [ ] **Bước 6:** `uv run pytest features/rising/tests/test_views.py tests/test_html_helper.py -q` → PASS.
- [ ] **Bước 7:** commit `test: bộ đọc HTML cho test, test điều hướng và nút bớt phụ thuộc vào markup`.

### Task 2: Phông Be Vietnam Pro và lính gác tài nguyên ngoài

**Files:**
- Create: `static/fonts/be-vietnam-pro/` 12 file `be-vietnam-pro-{400,500,600,700}-{latin,latin-ext,vietnamese}.woff2`,
  `static/fonts/be-vietnam-pro/OFL.txt`, `static/css/fonts.css`
- Modify: `tests/test_guards.py`

Nguồn (chủ dự án đã cho phép tải): 12 file woff2 mà Google Fonts phục vụ cho `Be Vietnam Pro:wght@400;500;600;700`
(tổng ~185 KB, đo ngày 23/11/2026), `OFL.txt` từ `google/fonts/ofl/bevietnampro/OFL.txt`. Ghi SHA-256 từng file
vào QĐ-20 (Task 5). `fonts.css` có 12 khối `@font-face` (`font-display: swap`, `unicode-range` chép đúng từ CSS của
Google Fonts), `src: url("../fonts/be-vietnam-pro/<file>")`.

- [ ] **Bước 1: test đỏ** trong `tests/test_guards.py`:
  - `test_static_assets_never_load_from_the_network` — mọi `.html`/`.css`/`.js` dưới `templates/`, `static/`,
    `features/*/templates/`: không khớp `(src|href)\s*=\s*["']https?://` trong thẻ `<script>`/`<link>`/`<img>`,
    `url\(\s*["']?https?://`, `@import`. (Link `<a href="https://github.com/…">` tới repo vẫn được phép.)
  - `test_bundled_font_has_license_and_all_subsets` — `OFL.txt` tồn tại và chứa "SIL Open Font License";
    `fonts.css` có đúng 12 `@font-face`, mỗi độ đậm 400/500/600/700 có đủ 3 bộ latin, latin-ext, vietnamese, mọi
    file trong `url()` tồn tại trên đĩa.
- [ ] **Bước 2:** chạy → FAIL (chưa có phông).
- [ ] **Bước 3:** tải 12 file + OFL vào đúng chỗ, đổi tên theo mẫu trên; viết `fonts.css`.
- [ ] **Bước 4:** `uv run pytest tests/test_guards.py -q` → PASS (kể cả test cấm TODO đọc được `OFL.txt` UTF-8).
- [ ] **Bước 5:** commit `chore: đóng gói phông Be Vietnam Pro (OFL), lính gác cấm tải tài nguyên từ mạng`.

### Task 3: Khung trang mới (thanh bên, token, JS tăng cường)

**Files:**
- Create: `tests/test_layout.py`, `static/js/app.js`
- Modify: `templates/base.html`, `static/css/app.css` (phần token, nền, khung trang), `tests/test_guards.py`

**Interfaces — Produces:** lớp khung `app`, `sidebar`, `brand`, `sidebar-nav`, `nav-item`, `sidebar-foot`, `main`;
block mới `{% block sidebar_extra %}` (rỗng). Thuộc tính JS: `data-autosubmit`, `data-clean-query`, `data-search`,
`data-confirm="<câu hỏi>"`.

- [ ] **Bước 1: test đỏ** `tests/test_layout.py` (tham số hoá trên `/`, `/scans/<id>/`, `/rising/`, `/rising/watch/`,
  `/rising/watch/<id>/`, `/repos/`):
  - `test_every_page_has_the_sidebar_with_one_current_item` — có `<aside class="sidebar"`, `nav_links` trả 4 mục,
    đúng một mục `current`.
  - `test_every_page_loads_app_js_deferred_and_local_fonts` — có `<script src="/static/js/app.js" defer>`, có
    `<link rel="stylesheet" href="/static/css/fonts.css">` trước `app.css`, có `<link rel="preload"` tới
    `/static/fonts/be-vietnam-pro/be-vietnam-pro-400-vietnamese.woff2` với `as="font"` và `crossorigin`.
  - `test_every_page_declares_light_and_dark` — có `<meta name="color-scheme" content="light dark">`.
  - Thêm vào `tests/test_guards.py`: `test_app_js_stays_small` — `static/js/app.js` tồn tại và ≤ 150 dòng.
- [ ] **Bước 2:** chạy → FAIL.
- [ ] **Bước 3:** `base.html` theo khung trong thiết kế (giữ block `title`, `head_extra`, `content`, logic
  `aria-current` y nguyên; bỏ `.tagline`, chân trang chuyển vào `sidebar-foot`). `app.css`: token sáng/tối, nền,
  khung lưới `240px 1fr`, ≤ 768px thanh bên thành thanh trên với hàng mục cuộn ngang. `app.js`:
  - thêm lớp `js` vào `<html>`;
  - `change` trên `select`, `input[type=checkbox|radio|number]` trong `form[data-autosubmit]` → `form.requestSubmit()`;
  - `submit` của `form[data-clean-query]` → tắt (`disabled`) các ô rỗng trước khi gửi;
  - `keydown` phím `/` không kèm Ctrl/Alt/Meta, khi `document.activeElement` không phải input/textarea/select/
    contenteditable → focus `[data-search]` đầu tiên, `preventDefault`;
  - `submit` của `form[data-confirm]` → `confirm(form.dataset.confirm)`, sai thì `preventDefault`.
- [ ] **Bước 4:** `uv run pytest tests/test_layout.py tests/test_guards.py features/rising/tests/test_views.py -q` → PASS.
- [ ] **Bước 5:** commit `feat: khung trang mới — thanh bên trái, token sáng/tối, JS tăng cường dần`.

### Task 4: Thành phần giao diện và áp lên mọi trang

**Files:**
- Modify: `static/css/app.css` (thành phần + phần riêng trang); mọi template trong `features/*/templates/`
  (`discovery/home.html`, `scan_detail.html`, `rising/report.html`, `watch.html`, `watch_edit.html`, `_today.html`,
  `_watch_form.html`, `_pager.html`, `browse/repos.html`, `scoring/_score.html`, `_suspicion.html`,
  `taxonomy/_labels.html`); `tests/test_layout.py`

Thành phần: `button` mặc định là viên thuốc đen; `.btn-secondary`/`button.secondary`, `.btn-ghost`, `.btn-sm`,
`:disabled` mờ .45; ô nhập cao 36px bo 8; `.search` (ô lớn, gợi ý `<kbd>/</kbd>`); `.chip`, `.chip-check`
(`:has(input:checked)`, ô tick gốc vẫn hiện); `.tabs`; bảng viền 1px bo 12, đầu bảng nền phụ, dòng hover; `.score`
mở ra thành khung nổi (`position: absolute`); `.badge`, `.status-*`; `.card` (viền 1px, bo 12, không bóng);
`.page-header`; `.empty`. Mỗi trang: bọc tiêu đề trong `<header class="page-header">`, thêm lớp; form lọc ở
`/rising/` và `/repos/` thêm `data-autosubmit data-clean-query`; ô `q` ở `/repos/` thêm `data-search` và lớp `search`.

- [ ] **Bước 1: test đỏ** trong `tests/test_layout.py`:
  - `test_autosubmit_forms_keep_a_submit_button` — trên mọi trang đã liệt kê, mỗi `Form` có `data-autosubmit` có ít
    nhất một nút (tắt JS vẫn lọc được), và có ít nhất một form như vậy ở `/rising/` và `/repos/`.
  - `test_browse_search_box_is_marked_for_the_slash_shortcut` — `/repos/` có `input` tên `q` mang `data-search`.
- [ ] **Bước 2:** chạy → FAIL.
- [ ] **Bước 3:** viết thành phần CSS, sửa từng template (chỉ lớp + `page-header` + thuộc tính `data-*`).
- [ ] **Bước 4:** `uv run poe test` → PASS toàn bộ (mọi test cũ không sửa vẫn xanh = không đổi hành vi).
- [ ] **Bước 5:** commit `feat: thành phần giao diện mới và áp lên mọi trang (không đổi hành vi)`.

### Task 5: Sổ sách

**Files:** `docs/ARCHITECTURE.md`, `CLAUDE.md`, `FEATURE_MAP.md`, `DEBT.md`, `TASKS.md`

- [ ] **Bước 1:** `docs/ARCHITECTURE.md`: thêm dòng QĐ-20 vào bảng mục 0, mục chi tiết QĐ-20 (giao diện vẫn render
  phía máy chủ; một CSS theo token sáng + tối tự động; `app.js` ≤ 150 dòng tăng cường dần, không thư viện, không
  HTMX, không CDN; phông Be Vietnam Pro OFL đóng gói sẵn, 12 file ~185 KB, SHA-256 từng file; được gì, tốn gì; đã
  loại HTMX, Tailwind, Google Fonts trực tuyến); sửa QĐ-05 trỏ sang QĐ-20; cây thư mục mục 3 thêm `static/js/`,
  `static/fonts/`.
- [ ] **Bước 2:** `CLAUDE.md` mục 3 thêm dòng "Tương tác trên trang | thuộc tính `data-*` + `static/js/app.js`
  (≤ 150 dòng, tắt JS vẫn dùng được) | `templates/base.html`"; mục 4 thêm dòng "Tải tài nguyên từ mạng trong
  template/CSS/JS | app chạy local, không phụ thuộc mạng ngoài | `tests/test_guards.py`".
- [ ] **Bước 3:** `FEATURE_MAP.md` bảng "Mô-đun lõi" thêm dòng `templates/base.html` + `static/` (khung trang, hệ
  thiết kế, JS tăng cường, phông) với test `tests/test_layout.py`.
- [ ] **Bước 4:** `DEBT.md` thêm D-010 (bảng + mục chi tiết 4 câu): `app.js` chưa có test tự động vì dự án không có
  trình chạy JS; kiểm bằng trình duyệt mỗi PR; trả khi JS vượt 150 dòng hoặc có QĐ duyệt công cụ test trình duyệt.
  Thêm `// DEBT(D-010): …` ở đầu `app.js`.
- [ ] **Bước 5:** `TASKS.md` thêm mục "Giao diện nền (PR A)" với các ô tick.
- [ ] **Bước 6:** `uv run poe check` → xanh. Commit `docs: QĐ-20 giao diện, nợ D-010, cập nhật bản đồ tính năng`.

### Task 6: Kiểm chứng và mở PR

- [ ] **Bước 1:** `uv run poe check` → xanh, ghi số test và độ phủ (trước PR: 825 test, 98,66%).
- [ ] **Bước 2:** chạy `uv run poe dev` trên bản sao CSDL thật (worktree riêng hoặc CSDL hiện tại chỉ đọc trang),
  mở bằng trình duyệt trong app ở 1440×900 và 375×812, nền sáng và tối, từng trang: `/`, một `/scans/<id>/`,
  `/rising/`, `/rising/watch/`, `/rising/watch/<id>/`, `/repos/`. Kiểm:
  - không lỗi console; `document.documentElement.scrollWidth <= innerWidth` ở 375px;
  - chữ tiếng Việt dùng Be Vietnam Pro (`document.fonts.check('14px "Be Vietnam Pro"')` và nhìn ảnh);
  - đổi ô chọn ở `/repos/` → trang tự lọc; gõ chữ ở ô tìm không tự gửi; phím `/` nhảy vào ô tìm, không cướp khi
    đang gõ ô khác; URL sau khi lọc không có ô rỗng;
  - tắt JS (chặn `app.js`) → bấm "Lọc" vẫn lọc;
  - mở bảng giải thích điểm, ẩn/hiện repo nghi star giả, lật trang ở `/rising/`.
- [ ] **Bước 3:** chụp ảnh từng trang làm bằng chứng; đẩy nhánh, mở PR với mô tả: làm gì, để được gì, kiểm thế nào
  (số liệu trên), phần chưa kiểm.
