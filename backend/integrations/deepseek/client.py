"""Small, bounded client for generating non-official giveaway comments.

The client is intentionally isolated from DOM and run state.  It accepts only
the scoped dynamic text supplied by runtime inspection, never logs the API key,
and retries only failures that are safe to retry before any Bilibili write.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from backend.config import Settings

_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_MAX_CONTEXT_CHARS = 4_000
_MAX_COMMENT_CHARS = 80


@dataclass(frozen=True, slots=True)
class DeepSeekCommentRequest:
    """Input sent to the model after page text has been scoped by the reader."""

    activity_text: str
    unofficial_type: str
    comment_instruction: str = ""
    required_topics: tuple[str, ...] = ()
    required_mention_count: int = 0


class DeepSeekCommentGenerationError(RuntimeError):
    """A safe, user-facing error returned before a Bilibili write is attempted."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        attempts: int = 0,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.attempts = attempts


class DeepSeekCommentGenerator:
    """Generate one short comment using the configured DeepSeek endpoint."""

    _system_prompt = (
        "你是中文社交评论助手，只生成一条自然、简短、与动态内容相关的评论。"
        "不要提及脚本、机器人、AI、自动化或保证中奖，不要使用引号、换行、列表、"
        "话题标签或@好友；动态要求的话题和@好友由程序按原格式追加。"
    )

    def __init__(
        self,
        settings: Settings,
        *,
        retry_delays_sec: tuple[float, ...] = (2.0, 5.0),
    ) -> None:
        self.settings = settings
        self.retry_delays_sec = retry_delays_sec

    async def generate(self, request: DeepSeekCommentRequest) -> str:
        """Return a normalized comment or a bounded, non-secret error."""

        api_key = self.settings.deepseek_api_key.strip()
        if not api_key:
            raise DeepSeekCommentGenerationError(
                "DEEPSEEK_NOT_CONFIGURED",
                "未配置 DeepSeek API Key，无法生成非官方抽奖评论",
            )

        attempts = max(1, min(3, int(self.settings.deepseek_max_attempts)))
        payload = self._payload(request)
        last_error: DeepSeekCommentGenerationError | None = None
        for attempt in range(1, attempts + 1):
            try:
                comment = await self._request_once(api_key, payload)
                return comment
            except DeepSeekCommentGenerationError as exc:
                last_error = DeepSeekCommentGenerationError(
                    exc.code,
                    exc.message,
                    retryable=exc.retryable,
                    attempts=attempt,
                )
            except (httpx.HTTPError, TimeoutError) as exc:
                last_error = DeepSeekCommentGenerationError(
                    "DEEPSEEK_NETWORK_ERROR",
                    f"DeepSeek 网络请求失败（{type(exc).__name__}）",
                    retryable=True,
                    attempts=attempt,
                )

            if last_error is None or not last_error.retryable or attempt >= attempts:
                break
            delay_index = min(attempt - 1, len(self.retry_delays_sec) - 1)
            delay = self.retry_delays_sec[delay_index] if self.retry_delays_sec else 0.0
            if delay > 0:
                await asyncio.sleep(delay)

        raise last_error or DeepSeekCommentGenerationError(
            "DEEPSEEK_COMMENT_GENERATION_FAILED",
            "DeepSeek 评论生成失败",
            attempts=attempts,
        )

    def _payload(self, request: DeepSeekCommentRequest) -> dict[str, object]:
        kind = "转发加码抽奖" if request.unofficial_type == "boosted" else "普通互动抽奖"
        context = _normalize(request.activity_text)[:_MAX_CONTEXT_CHARS]
        if not context:
            context = "动态正文未能读取"
        return {
            "model": self.settings.deepseek_model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"这是一个{kind}动态。请根据动态内容生成一条 10 到 35 个汉字左右的"
                        "真诚评论，只输出评论正文，不要复述参与规则。\n\n动态内容：\n"
                        f"{context}"
                    ),
                },
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.8,
            "max_tokens": 80,
            "stream": False,
        }

    async def _request_once(self, api_key: str, payload: dict[str, object]) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        timeout = max(1.0, float(self.settings.deepseek_timeout_sec))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                self.settings.deepseek_api_url,
                headers=headers,
                json=payload,
            )
        if response.status_code < 200 or response.status_code >= 300:
            retryable = response.status_code in _RETRYABLE_STATUS_CODES
            suffix = _safe_error_detail(response).replace(api_key, "[REDACTED]")
            message = f"DeepSeek 请求失败（HTTP {response.status_code}）"
            if suffix:
                message = f"{message}：{suffix}"
            raise DeepSeekCommentGenerationError(
                "DEEPSEEK_HTTP_ERROR",
                message,
                retryable=retryable,
            )

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise DeepSeekCommentGenerationError(
                "DEEPSEEK_RESPONSE_INVALID",
                "DeepSeek 返回内容不是有效 JSON",
                retryable=True,
            ) from exc
        content = _message_content(data)
        comment = _normalize_generated_comment(content)
        if not comment:
            raise DeepSeekCommentGenerationError(
                "DEEPSEEK_COMMENT_EMPTY",
                "DeepSeek 未返回有效评论",
                retryable=True,
            )
        return comment


def _message_content(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _normalize_generated_comment(value: str) -> str:
    text = _normalize(value)
    text = re.sub(r"^```(?:text|plaintext)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```$", "", text).strip()
    text = text.strip("\"'“”‘’「」")
    if len(text) > _MAX_COMMENT_CHARS:
        text = f"{text[: _MAX_COMMENT_CHARS - 1]}…"
    return text


def _normalize(value: str) -> str:
    return " ".join(value.replace("\u200b", "").replace("\ufeff", "").split())


def _safe_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        detail = error.get("message")
    else:
        detail = error or data.get("message")
    if not isinstance(detail, str):
        return ""
    return _normalize(detail)[:160]


__all__ = [
    "DeepSeekCommentGenerationError",
    "DeepSeekCommentGenerator",
    "DeepSeekCommentRequest",
]
