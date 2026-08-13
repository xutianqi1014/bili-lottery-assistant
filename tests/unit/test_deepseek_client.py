from __future__ import annotations

import httpx
import pytest
import respx

from backend.config import Settings
from backend.integrations.deepseek import (
    DeepSeekCommentGenerationError,
    DeepSeekCommentGenerator,
    DeepSeekCommentRequest,
)


def _request() -> DeepSeekCommentRequest:
    return DeepSeekCommentRequest(
        activity_text="转发并关注，抽取夏日礼物 #夏日活动#",
        unofficial_type="normal",
        required_topics=("#夏日活动#",),
        required_mention_count=1,
    )


@pytest.mark.asyncio
@respx.mock
async def test_generates_short_comment_without_sending_secret_in_prompt():
    route = respx.post("https://api.test/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "这个活动很有诚意，感谢分享！"}}]},
        )
    )
    settings = Settings(
        deepseek_api_key="sk-secret-value",
        deepseek_api_url="https://api.test/chat/completions",
        deepseek_timeout_sec=1,
    )

    result = await DeepSeekCommentGenerator(settings).generate(_request())

    assert result == "这个活动很有诚意，感谢分享！"
    assert route.called
    request_body = route.calls[0].request.content.decode()
    assert "sk-secret-value" not in request_body
    assert "转发并关注" in request_body


@pytest.mark.asyncio
@respx.mock
async def test_retries_transient_http_failure_before_returning_comment():
    route = respx.post("https://api.test/chat/completions").mock(
        side_effect=[
            httpx.Response(503, json={"error": {"message": "busy"}}),
            httpx.Response(200, json={"choices": [{"message": {"content": "祝活动顺利！"}}]}),
        ]
    )
    settings = Settings(
        deepseek_api_key="sk-test",
        deepseek_api_url="https://api.test/chat/completions",
        deepseek_timeout_sec=1,
        deepseek_max_attempts=2,
    )

    generator = DeepSeekCommentGenerator(settings, retry_delays_sec=(0, 0))
    assert await generator.generate(_request()) == "祝活动顺利！"
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_missing_key_is_reported_before_network_call():
    settings = Settings(deepseek_api_key="")

    with pytest.raises(DeepSeekCommentGenerationError) as error:
        await DeepSeekCommentGenerator(settings).generate(_request())

    assert error.value.code == "DEEPSEEK_NOT_CONFIGURED"
    assert error.value.attempts == 0
