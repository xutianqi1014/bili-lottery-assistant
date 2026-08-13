"""DOM transport for exactly one source-article like and terminal readback."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from .selectors import ARTICLE_LIKE, ARTICLE_LIKE_ACTIVE
from .source_like import (
    SourceLikeOutcomeState,
    SourceLikeWriteResult,
    validate_source_like_target,
)

SOURCE_LIKE_SELECTOR = ARTICLE_LIKE
SOURCE_LIKE_ACTIVE_SELECTOR = ARTICLE_LIKE_ACTIVE
SOURCE_LIKE_SELECTOR_VERSION = "source_like_dom_v1"


class SourceLikePage(Protocol):
    async def wait_for_selector(self, selector: str, *, timeout: int) -> Any: ...

    def locator(self, selector: str) -> Any: ...


class SourceLikeBrowser(Protocol):
    async def open(self, url: str) -> SourceLikePage: ...


class DomSourceLikeTransport:
    """Click the article like button and verify the active class afterward.

    The caller must authorize a run-scoped target before constructing this
    transport.  A timeout after the click is always returned as ``UNKNOWN``
    because the click may have reached Bilibili.
    """

    def __init__(self, browser: SourceLikeBrowser, timeout_ms: int = 15_000):
        self.browser = browser
        self.timeout_ms = timeout_ms

    async def perform(
        self,
        *,
        target_url: str,
        payload: Mapping[str, object],
    ) -> SourceLikeWriteResult:
        del payload
        validate_source_like_target(target_url)
        try:
            page = await self.browser.open(target_url)
            await page.wait_for_selector(SOURCE_LIKE_SELECTOR, timeout=self.timeout_ms)
        except Exception as exc:  # noqa: BLE001 - page state is not reliable
            return SourceLikeWriteResult(
                SourceLikeOutcomeState.UNKNOWN,
                "SOURCE_LIKE_PAGE_READ_UNKNOWN",
                f"来源专栏点赞按钮读取结果未知（{type(exc).__name__}）",
            )

        try:
            if await page.locator(SOURCE_LIKE_ACTIVE_SELECTOR).count() > 0:
                return SourceLikeWriteResult(
                    SourceLikeOutcomeState.ALREADY_DONE,
                    "SOURCE_ALREADY_LIKED",
                    "来源专栏已经点赞，无需重复操作",
                )
            button = page.locator(SOURCE_LIKE_SELECTOR)
            button_count = await button.count()
        except Exception as exc:  # noqa: BLE001 - selector state is uncertain
            return SourceLikeWriteResult(
                SourceLikeOutcomeState.UNKNOWN,
                "SOURCE_LIKE_BUTTON_READ_UNKNOWN",
                f"来源专栏点赞按钮状态未知（{type(exc).__name__}）",
            )

        if button_count == 0:
            return SourceLikeWriteResult(
                SourceLikeOutcomeState.FAILED,
                "SOURCE_LIKE_BUTTON_NOT_FOUND",
                "来源专栏点赞按钮不存在，未执行点击",
            )
        if button_count != 1:
            return SourceLikeWriteResult(
                SourceLikeOutcomeState.FAILED,
                "SOURCE_LIKE_BUTTON_AMBIGUOUS",
                "来源专栏点赞按钮数量不明确，未执行点击",
            )

        try:
            await button.click(timeout=self.timeout_ms)
        except Exception as exc:  # noqa: BLE001 - click may have reached server
            return SourceLikeWriteResult(
                SourceLikeOutcomeState.UNKNOWN,
                "SOURCE_LIKE_CLICK_UNKNOWN",
                f"来源专栏点赞点击结果未知（{type(exc).__name__}）",
            )

        try:
            await page.wait_for_selector(
                SOURCE_LIKE_ACTIVE_SELECTOR,
                timeout=self.timeout_ms,
            )
            active_count = await page.locator(SOURCE_LIKE_ACTIVE_SELECTOR).count()
        except Exception as exc:  # noqa: BLE001 - server-side result is uncertain
            return SourceLikeWriteResult(
                SourceLikeOutcomeState.UNKNOWN,
                "SOURCE_LIKE_TERMINAL_STATE_UNKNOWN",
                f"来源专栏点赞终态无法确认（{type(exc).__name__}）",
            )
        if active_count > 0:
            return SourceLikeWriteResult(
                SourceLikeOutcomeState.SUCCESS,
                "SOURCE_LIKE_CONFIRMED",
                "来源专栏点赞已通过 DOM 终态确认",
            )
        return SourceLikeWriteResult(
            SourceLikeOutcomeState.UNKNOWN,
            "SOURCE_LIKE_TERMINAL_STATE_UNKNOWN",
            "来源专栏点赞后未检测到已点赞终态",
        )
