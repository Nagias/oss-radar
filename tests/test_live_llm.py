"""Test gọi 9router THẬT — chỉ chạy bằng `uv run poe test-live`, không chạy trong CI.

Mục đích: phát hiện sớm khi 9router hay model đổi định dạng trả lời. Tốn 1 lượt gọi AI
(~2.300 token).
Chưa điền `LLM_API_KEY` thì bỏ qua.
"""

import pytest

from integrations.llm.client import get_llm_client, llm_configured

pytestmark = pytest.mark.live


def test_live_llm_answers_one_json_block() -> None:
    if not llm_configured():
        pytest.skip("Chưa có LLM_API_KEY trong .env")
    messages = [{"role": "user", "content": 'Trả về đúng JSON {"ok": true}, không thêm gì khác.'}]

    with get_llm_client() as llm:
        result = llm.complete(messages)

    assert '"ok"' in result.content
    assert result.prompt_tokens > 0
    assert result.completion_tokens > 0
