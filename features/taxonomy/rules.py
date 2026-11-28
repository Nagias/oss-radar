"""Luật phân loại không cần AI — hàm thuần (không CSDL, không mạng).

Thiết kế bộ luật 2026-11-28, Luật B ("Làm được gì") và Luật C ("Dành cho ai"). Mọi kết luận kèm lý
do: danh sách từ khoá đã khớp. Không nhóm nào đủ điểm thì trả `None` — không ép vào "Khác", để repo
vẫn nằm ở mục "Chưa phân loại" và AI (khi có) còn thấy nó.
"""

import re
from dataclasses import dataclass

from features.taxonomy.categories import OTHER, Taxonomy
from features.taxonomy.keywords import GroupKeywords, Keywords
from features.taxonomy.prompt import MAX_ASPECTS, MAX_AUDIENCE, MAX_REASON, Labels, RepoForPrompt

STRONG_POINTS = 2
WEAK_POINTS = 1
ASPECT_MIN_POINTS = 2  # một từ mạnh, hoặc hai từ yếu
DERIVED_POINTS = 2  # "Dành cho ai" suy từ nhóm "Làm được gì" đã chọn
DERIVED_POINTS_BY_AUDIENCE = {"gamedev": 3}  # repo game gần như luôn dành cho người làm game
AUDIENCE_MIN_POINTS = 3  # hai dấu hiệu độc lập: ưu tiên đúng hơn đủ (nhãn dùng để gợi ý)
AUDIENCE_MIN_POINTS_BY_CODE = {"developer": 2}
REASON_PREFIX = "Luật: "
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class _Match:
    code: str
    points: int
    keywords: tuple[str, ...]


def classify_by_rules(repo: RepoForPrompt, keywords: Keywords, taxonomy: Taxonomy) -> Labels | None:
    """Nhãn của một repo theo bộ từ khoá; `None` khi không nhóm "Làm được gì" nào đủ điểm."""
    text = _Text.of(repo)
    aspects = _top(
        [
            match
            for category in taxonomy.aspects
            if category.code != OTHER
            and (match := _match(category.code, keywords.aspects.get(category.code), text))
            and match.points >= ASPECT_MIN_POINTS
        ],
        MAX_ASPECTS,
    )
    if not aspects:
        return None
    chosen = {match.code for match in aspects}
    audience = _top(
        [
            match
            for category in taxonomy.audience
            if (match := _audience_match(category.code, keywords, chosen, text))
            and match.points >= AUDIENCE_MIN_POINTS_BY_CODE.get(category.code, AUDIENCE_MIN_POINTS)
        ],
        MAX_AUDIENCE,
    )
    return Labels(
        audience=tuple(match.code for match in audience),
        aspects=tuple(match.code for match in aspects),
        reason=_reason([*aspects, *audience]),
    )


@dataclass(frozen=True, slots=True)
class _Text:
    """Chữ của repo ở hai dạng: chuỗi từ nối bằng `-` (khớp nguyên từ), chữ thường (chữ Hán)."""

    slugs: str
    raw: str

    @classmethod
    def of(cls, repo: RepoForPrompt) -> "_Text":
        name = repo.full_name.rpartition("/")[2]
        sources = [*repo.topics, name, repo.description]
        slugs = "|".join(_slug(source) for source in sources)
        return cls(slugs=slugs, raw=" ".join(sources).lower())

    def has(self, keyword: str) -> bool:
        if not keyword.isascii():
            return keyword in self.raw  # tiếng Trung không có dấu cách giữa các từ
        return _slug(keyword) in self.slugs


def _slug(text: str) -> str:
    """`Text to Video!` → `-text-to-video-`: so chuỗi con trên dạng này là so nguyên từ."""
    return "-" + "-".join(_WORD.findall(text.lower())) + "-"


def _match(code: str, group: GroupKeywords | None, text: _Text) -> _Match | None:
    if group is None:
        return None
    found = [word for word in (*group.strong, *group.weak) if text.has(word)]
    # `claude-code` đã khớp thì `code` nằm trong nó không được tính thêm (cũng như 视频 trong
    # 短视频): một dấu hiệu chỉ cho điểm một lần.
    kept = {word for word in found if not any(_inside(word, other) for other in found)}
    strong = tuple(word for word in group.strong if word in kept)
    weak = tuple(word for word in group.weak if word in kept)
    if not strong and not weak:
        return None
    points = STRONG_POINTS * len(strong) + WEAK_POINTS * len(weak)
    return _Match(code=code, points=points, keywords=(*strong, *weak))


def _inside(word: str, other: str) -> bool:
    if word == other:
        return False
    if word.isascii() and other.isascii():
        return _slug(word) in _slug(other)
    return word in other


def _audience_match(code: str, keywords: Keywords, chosen: set[str], text: _Text) -> _Match | None:
    own = _match(code, keywords.audience.get(code), text)
    points = own.points if own else 0
    if chosen.intersection(keywords.derived.get(code, ())):
        points += DERIVED_POINTS_BY_AUDIENCE.get(code, DERIVED_POINTS)
    if points == 0:
        return None
    return _Match(code=code, points=points, keywords=own.keywords if own else ())


def _top(matches: list[_Match], limit: int) -> list[_Match]:
    """Điểm cao trước; bằng điểm thì giữ thứ tự của bộ nhóm (sorted ổn định)."""
    return sorted(matches, key=lambda match: -match.points)[:limit]


def _reason(matches: list[_Match]) -> str:
    seen: list[str] = []
    for match in matches:
        for keyword in match.keywords:
            if keyword not in seen:
                seen.append(keyword)
    reason = REASON_PREFIX + ", ".join(seen)
    if len(reason) <= MAX_REASON:
        return reason
    return reason[: MAX_REASON - 1].rstrip(", ") + "…"
