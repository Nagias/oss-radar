"""Form quét: kiểm tra dữ liệu nhập TRƯỚC khi tốn một lần gọi GitHub."""

import pytest

from features.discovery.forms import ScanForm


def test_query_is_trimmed() -> None:
    form = ScanForm(data={"query": "   topic:ai-agent  "})

    assert form.is_valid()
    assert form.cleaned_data["query"] == "topic:ai-agent"


@pytest.mark.parametrize("query", ["", "    "])
def test_blank_query_is_rejected_with_vietnamese_message(query: str) -> None:
    form = ScanForm(data={"query": query})

    assert not form.is_valid()
    assert form.errors["query"] == ["Hãy nhập truy vấn tìm kiếm GitHub."]


def test_query_longer_than_github_limit_is_rejected() -> None:
    form = ScanForm(data={"query": "a" * 257})

    assert not form.is_valid()
    assert "256" in form.errors["query"][0]
