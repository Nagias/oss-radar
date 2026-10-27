"""Client AI (9router): đọc phản hồi thật, gửi đúng tham số, mọi kiểu hỏng thành lỗi có tên.

`tests/fixtures/llm/chat_completion_classify.json` là phản hồi THẬT của 9router (2026-10-27).
"""

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from pytest_django.fixtures import Settings

from integrations.github.pacing import CallBudget, CallBudgetExhaustedError, RequestPacer
from integrations.llm.client import LlmClient, get_llm_client, llm_configured
from integrations.llm.errors import (
    LlmAuthError,
    LlmNotConfiguredError,
    LlmRateLimitError,
    LlmResponseError,
    LlmUnavailableError,
)
from tests.factories import load_fixture
from tests.fakes import FakeTime

BASE_URL = "http://localhost:20128/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"
MESSAGES = [{"role": "user", "content": "Phân loại repo"}]


def real_reply() -> dict[str, Any]:
    return load_fixture("llm/chat_completion_classify.json")


def make_client(clock: FakeTime, *, budget: CallBudget | None = None) -> LlmClient:
    pacer = RequestPacer(
        min_interval=0.0,
        sleep=clock.sleep,
        clock=clock.monotonic,
        wall_clock=clock.time,
        jitter=lambda: 0.0,
    )
    return LlmClient(
        base_url=BASE_URL,
        api_key="khoa-thu",
        model="ag/gemini-3.8-flash-low",
        timeout_seconds=5.0,
        pacer=pacer,
        budget=budget,
    )


@pytest.fixture
def client(fake_time: FakeTime) -> Iterator[LlmClient]:
    with make_client(fake_time) as llm:
        yield llm


def test_complete_parses_real_reply(client: LlmClient, http_mock: respx.MockRouter) -> None:
    http_mock.post(CHAT_URL).respond(json=real_reply())

    result = client.complete(MESSAGES)

    assert result.content.startswith("```json")
    assert '"aspects": ["video", "writing"]' in result.content
    assert (result.prompt_tokens, result.completion_tokens) == (2285, 137)
    assert result.model == "gemini-3.8-flash-n"


def test_complete_sends_key_model_and_asks_for_one_json_block(
    client: LlmClient, http_mock: respx.MockRouter
) -> None:
    route = http_mock.post(CHAT_URL).respond(json=real_reply())

    client.complete(MESSAGES)

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer khoa-thu"
    body = json.loads(request.content)
    assert body["model"] == "ag/gemini-3.8-flash-low"
    assert body["messages"] == MESSAGES
    assert body["stream"] is False  # 9router mặc định trả dạng luồng (đo 2026-10-27)
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_raises_auth_error(
    client: LlmClient, http_mock: respx.MockRouter, status: int
) -> None:
    http_mock.post(CHAT_URL).respond(status, json={"error": {"message": "Invalid API key"}})

    with pytest.raises(LlmAuthError, match="Invalid API key"):
        client.complete(MESSAGES)


def test_rate_limited_waits_then_succeeds(
    client: LlmClient, http_mock: respx.MockRouter, fake_time: FakeTime
) -> None:
    route = http_mock.post(CHAT_URL)
    route.side_effect = [
        httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "slow"}}),
        httpx.Response(200, json=real_reply()),
    ]

    client.complete(MESSAGES)

    assert 7.0 in fake_time.sleeps
    assert route.call_count == 2


def test_rate_limited_four_times_raises(client: LlmClient, http_mock: respx.MockRouter) -> None:
    route = http_mock.post(CHAT_URL).respond(429, json={"error": {"message": "quota"}})

    with pytest.raises(LlmRateLimitError):
        client.complete(MESSAGES)

    assert route.call_count == 4


def test_rate_limit_asking_to_wait_too_long_raises_named_error(
    client: LlmClient, http_mock: respx.MockRouter
) -> None:
    http_mock.post(CHAT_URL).respond(429, headers={"retry-after": "3600"}, json={})

    with pytest.raises(LlmRateLimitError):
        client.complete(MESSAGES)


def test_server_errors_retried_three_times_then_raise(
    client: LlmClient, http_mock: respx.MockRouter
) -> None:
    route = http_mock.post(CHAT_URL).respond(503, text="down")

    with pytest.raises(LlmUnavailableError):
        client.complete(MESSAGES)

    assert route.call_count == 4
    assert client.calls_made == 4  # mọi lượt gửi đi đều được đếm


def test_network_failure_raises_unavailable(client: LlmClient, http_mock: respx.MockRouter) -> None:
    http_mock.post(CHAT_URL).mock(side_effect=httpx.ConnectError("9router tắt"))

    with pytest.raises(LlmUnavailableError, match="9router"):
        client.complete(MESSAGES)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="data: {...}\n\n"),  # trả dạng luồng thay vì JSON
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "x"}}], "usage": "lạ"}),
    ],
)
def test_malformed_reply_raises_response_error(
    client: LlmClient, http_mock: respx.MockRouter, response: httpx.Response
) -> None:
    http_mock.post(CHAT_URL).mock(return_value=response)

    with pytest.raises(LlmResponseError):
        client.complete(MESSAGES)


def test_missing_usage_counts_zero_tokens(client: LlmClient, http_mock: respx.MockRouter) -> None:
    reply = real_reply()
    del reply["usage"]
    http_mock.post(CHAT_URL).respond(json=reply)

    result = client.complete(MESSAGES)

    assert (result.prompt_tokens, result.completion_tokens) == (0, 0)


def test_every_call_spends_budget(http_mock: respx.MockRouter, fake_time: FakeTime) -> None:
    route = http_mock.post(CHAT_URL).respond(json=real_reply())

    with make_client(fake_time, budget=CallBudget(1)) as llm:
        llm.complete(MESSAGES)
        with pytest.raises(CallBudgetExhaustedError):
            llm.complete(MESSAGES)

    assert route.call_count == 1
    assert llm.calls_made == 1  # hết ngân sách: không gửi, không đếm


def test_get_llm_client_reads_settings(settings: Settings, http_mock: respx.MockRouter) -> None:
    settings.LLM_API_KEY = "khoa-cau-hinh"
    settings.LLM_BASE_URL = "http://may-khac:9000/v1"
    settings.LLM_MODEL = "model-thu"
    route = http_mock.post("http://may-khac:9000/v1/chat/completions").respond(json=real_reply())

    with get_llm_client() as llm:
        llm.complete(MESSAGES)

    assert route.calls.last.request.headers["Authorization"] == "Bearer khoa-cau-hinh"
    assert json.loads(route.calls.last.request.content)["model"] == "model-thu"
    assert llm_configured() is True


def test_get_llm_client_without_key_refuses(settings: Settings) -> None:
    settings.LLM_API_KEY = ""

    assert llm_configured() is False
    with pytest.raises(LlmNotConfiguredError, match="LLM_API_KEY"):
        get_llm_client()
