"""Chia lát truy vấn để vượt trần 1.000 kết quả/truy vấn của GitHub. Toàn hàm thuần, không gọi mạng.

Một lát = truy vấn của người dùng + một khoảng ngày tạo + một khoảng star. Lát nào GitHub báo
quá 1.000 kết quả thì chia đôi: còn nhiều ngày thì chia theo ngày (nửa MỚI làm trước), còn đúng
một ngày thì chia theo star (nửa star CAO làm trước) — để nếu hết ngân sách giữa chừng thì phần
lấy được có giá trị nhất.
"""

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta

PER_PAGE = 100  # GitHub trả tối đa 100 kết quả mỗi trang.
MAX_RESULTS_PER_QUERY = 1000  # GitHub chỉ cho xem 1.000 kết quả đầu của một truy vấn.
EARLIEST_DATE = date(2008, 1, 1)  # GitHub ra đời năm 2008: không có repo nào tạo trước đó.

# Đứng đầu truy vấn hoặc sau khoảng trắng/ngoặc, có thể kèm dấu phủ định "-" (vd `-stars:>5`).
_FORBIDDEN = re.compile(r"(?:^|(?<=[\s(]))-?(stars|created|sort):", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SliceRange:
    created_from: date
    created_to: date
    stars_min: int
    stars_max: int | None  # None = không giới hạn trên


def resolve_root_range(
    *,
    created_from: date | None,
    created_to: date | None,
    min_stars: int,
    max_stars: int | None,
    today: date,
) -> SliceRange:
    """Lát gốc của một lần quét: ngày để trống nghĩa là từ 2008-01-01 tới hôm nay."""
    return SliceRange(created_from or EARLIEST_DATE, created_to or today, min_stars, max_stars)


def build_query(user_query: str, rng: SliceRange) -> str:
    """Truy vấn gửi GitHub cho một lát — luôn có đúng một điều kiện `stars:` và một `created:`."""
    if rng.stars_max is None:
        stars = f"stars:>={rng.stars_min}"
    else:
        stars = f"stars:{rng.stars_min}..{rng.stars_max}"
    created = f"created:{rng.created_from.isoformat()}..{rng.created_to.isoformat()}"
    return f"{user_query.strip()} {stars} {created}"


def split(rng: SliceRange, *, top_stars: int) -> tuple[SliceRange, SliceRange] | None:
    """Chia lát làm hai, trả (làm trước, làm sau); không chia được nữa thì trả None.

    `top_stars` là số star cao nhất thấy ở trang 1 của lát (trang sắp theo star giảm dần), dùng làm
    cận trên khi lát không có star tối đa.
    """
    days = (rng.created_to - rng.created_from).days
    if days >= 1:
        middle = rng.created_from + timedelta(days=days // 2)
        older = SliceRange(rng.created_from, middle, rng.stars_min, rng.stars_max)
        newer = SliceRange(middle + timedelta(days=1), rng.created_to, rng.stars_min, rng.stars_max)
        return newer, older

    upper = rng.stars_max if rng.stars_max is not None else top_stars
    if upper <= rng.stars_min:
        return None
    middle_stars = (rng.stars_min + upper) // 2
    day = rng.created_from
    higher = SliceRange(day, day, middle_stars + 1, upper)
    lower = SliceRange(day, day, rng.stars_min, middle_stars)
    return higher, lower


def pages_needed(total_count: int) -> int:
    """Số trang phải lấy để có đủ kết quả của một lát (tối đa 10 trang = 1.000 kết quả)."""
    return min(math.ceil(total_count / PER_PAGE), MAX_RESULTS_PER_QUERY // PER_PAGE)


def find_forbidden_qualifier(query: str) -> str | None:
    """Điều kiện người dùng không được tự ghi vì app tự thêm (`stars:`, `created:`, `sort:`)."""
    found = _FORBIDDEN.search(query)
    return f"{found.group(1).lower()}:" if found else None
