"""Luật phân loại không cần AI (thiết kế bộ luật 2026-11-28, Luật B và C) — hàm thuần."""

from features.taxonomy import rules
from features.taxonomy.categories import load_taxonomy
from features.taxonomy.keywords import GroupKeywords, Keywords, load_keywords
from features.taxonomy.prompt import MAX_REASON, Labels, RepoForPrompt
from features.taxonomy.rules import classify_by_rules


def group(strong: tuple[str, ...] = (), weak: tuple[str, ...] = ()) -> GroupKeywords:
    return GroupKeywords(strong=strong, weak=weak)


KEYWORDS = Keywords(
    version=1,
    aspects={
        "video": group(("text-to-video", "短视频"), ("video", "ffmpeg", "subtitle")),
        "image": group(("comfyui",), ("image", "photo")),
        "audio": group(("tts",), ("voice",)),
        "agent": group(("ai-agent",), ("agent", "mcp")),
        "devtools": group(("cli",), ("code",)),
        "game": group(("game-engine",), ("game",)),
        "ads": group(("google-ads",), ("ads",)),
    },
    audience={
        "creator": group(("youtube",), ("creator",)),
        "marketer": group(("seo",), ("marketing",)),
        "developer": group(("sdk",), ("library",)),
        "gamedev": group((), ("unity",)),
        "research": group(("arxiv",), ("paper", "benchmark")),
    },
    derived={
        "creator": ("video", "image", "audio"),
        "marketer": ("ads",),
        "developer": ("devtools",),
        "gamedev": ("game",),
    },
)


def repo(
    *, topics: tuple[str, ...] = (), description: str = "", name: str = "someone/project"
) -> RepoForPrompt:
    return RepoForPrompt(
        id=1, full_name=name, description=description, topics=topics, language="Python"
    )


def classify(
    *, topics: tuple[str, ...] = (), description: str = "", name: str = "someone/project"
) -> Labels | None:
    fields = repo(topics=topics, description=description, name=name)
    return classify_by_rules(fields, KEYWORDS, load_taxonomy())


# --- Luật B: "Làm được gì" -------------------------------------------------------------------


def test_one_strong_keyword_is_enough() -> None:
    labels = classify(topics=("comfyui",))

    assert labels is not None
    assert labels.aspects == ("image",)


def test_one_weak_keyword_is_not_enough_but_two_are() -> None:
    assert classify(topics=("video",)) is None

    labels = classify(topics=("video", "ffmpeg"))
    assert labels is not None
    assert labels.aspects == ("video",)


def test_keyword_matches_whole_words_only() -> None:
    # "agents" không phải "agent", "videography" không phải "video", "recode" không phải "code".
    assert classify(topics=("agents", "videography"), description="recode mcpx") is None


def test_keyword_matches_inside_a_longer_topic_and_in_the_repo_name() -> None:
    labels = classify(topics=("awesome-text-to-video-list",))
    assert labels is not None
    assert labels.aspects == ("video",)

    labels = classify(name="someone/ComfyUI_Nodes")
    assert labels is not None
    assert labels.aspects == ("image",)


def test_multi_word_keyword_matches_spaced_words_in_description() -> None:
    labels = classify(description="A Text to Video pipeline.")

    assert labels is not None
    assert labels.aspects == ("video",)


def test_chinese_keyword_matches_as_substring() -> None:
    labels = classify(description="一键生成短视频的工具")

    assert labels is not None
    assert labels.aspects == ("video",)


def test_the_same_keyword_counts_once_even_if_seen_in_topic_and_description() -> None:
    assert classify(topics=("video",), description="video video video") is None


def test_no_group_matches_returns_none_not_other() -> None:
    assert classify(topics=("cooking",), description="Recipes for dinner") is None


def test_at_most_three_groups_highest_points_first() -> None:
    labels = classify(
        topics=("comfyui", "image", "text-to-video", "ai-agent", "agent", "mcp", "cli", "tts")
    )

    assert labels is not None
    # agent 3 điểm (ai-agent + mcp; `agent` nằm trong `ai-agent` nên không tính thêm), image 3
    # (comfyui + image); các nhóm 2 điểm theo thứ tự trong bộ nhóm: video trước audio, devtools.
    assert labels.aspects == ("agent", "image", "video")


def test_keyword_inside_another_matched_keyword_is_not_counted_twice() -> None:
    # Topic `text-to-video` chứa cả từ yếu `video`: vẫn chỉ là một dấu hiệu. Hai từ yếu thật sự
    # khác nhau mới đủ điểm.
    labels = classify(topics=("ai-agent",))
    assert labels is not None
    assert labels.reason == "Luật: ai-agent"

    assert classify(description="一条视频") is None  # KEYWORDS chỉ có 短视频 (mạnh), không có 视频


# --- Luật C: "Dành cho ai" -------------------------------------------------------------------


def test_audience_needs_two_independent_signals() -> None:
    # Chỉ suy từ nhóm "Ảnh" (+2) thì chưa đủ 3 điểm.
    only_derived = classify(topics=("comfyui",))
    assert only_derived is not None
    assert only_derived.audience == ()

    # Suy từ nhóm (+2) cộng một từ khoá yếu của "Sáng tạo" (+1) = 3 điểm.
    labels = classify(topics=("comfyui",), description="for every creator")
    assert labels is not None
    assert labels.audience == ("creator",)


def test_audience_from_own_keywords_alone() -> None:
    # Từ khoá mạnh (+2) và yếu (+1) của Marketer, không có nhóm "Làm được gì" nào suy ra nó.
    labels = classify(topics=("seo", "marketing", "comfyui"))

    assert labels is not None
    assert labels.audience == ("marketer",)


def test_developer_needs_only_two_points() -> None:
    labels = classify(topics=("cli",))

    assert labels is not None
    assert labels.aspects == ("devtools",)
    assert labels.audience == ("developer",)


def test_game_derives_gamedev_on_its_own() -> None:
    labels = classify(topics=("game-engine",))

    assert labels is not None
    assert labels.audience == ("gamedev",)


def test_at_most_two_audiences_highest_points_first() -> None:
    labels = classify(
        topics=("cli", "sdk", "comfyui", "youtube", "creator", "google-ads", "seo"),
    )

    assert labels is not None
    # creator: 2 (suy) + 2 + 1 = 5; developer: 2 (suy) + 2 = 4; marketer: 2 (suy) + 2 = 4 → xếp sau
    # developer vì bộ nhóm liệt kê developer trước.
    assert labels.audience == ("creator", "developer")


def test_audience_keywords_do_not_classify_a_repo_without_aspects() -> None:
    # Không nhóm "Làm được gì" nào đủ điểm thì không gắn gì cả, dù có từ khoá "Dành cho ai".
    assert classify(topics=("seo", "marketing", "arxiv")) is None


# --- Lý do ---------------------------------------------------------------------------------


def test_reason_lists_matched_keywords() -> None:
    labels = classify(topics=("comfyui",), description="for every creator on youtube")

    assert labels is not None
    assert labels.reason.startswith("Luật: ")
    for keyword in ("comfyui", "creator", "youtube"):
        assert keyword in labels.reason


def test_reason_is_capped() -> None:
    labels = classify(
        topics=("comfyui", "image", "photo", "text-to-video", "video", "ffmpeg", "subtitle"),
        description="ai-agent agent mcp cli code tts voice youtube creator seo marketing sdk",
    )

    assert labels is not None
    assert len(labels.reason) <= MAX_REASON


# --- File thật -------------------------------------------------------------------------------


def test_real_keywords_classify_typical_repos() -> None:
    taxonomy, real = load_taxonomy(), load_keywords()

    comfy = classify_by_rules(
        repo(topics=("comfyui", "stable-diffusion"), description="Custom nodes for ComfyUI"),
        real,
        taxonomy,
    )
    assert comfy is not None
    assert "image" in comfy.aspects

    mcp = classify_by_rules(
        repo(topics=("mcp-server", "claude-code"), description="An MCP server for Postgres"),
        real,
        taxonomy,
    )
    assert mcp is not None
    assert "devtools" in mcp.aspects
    assert "developer" in mcp.audience

    assert classify_by_rules(repo(description="My dotfiles"), real, taxonomy) is None


def test_point_tables_use_real_codes() -> None:
    taxonomy = load_taxonomy()

    assert set(rules.DERIVED_POINTS_BY_AUDIENCE) <= taxonomy.codes("audience")
    assert set(rules.AUDIENCE_MIN_POINTS_BY_CODE) <= taxonomy.codes("audience")
