from typing import Any

from backend.domain.entities import MarkerInspection, SourceArticleCandidate
from backend.domain.enums import LikeState
from backend.domain.ports import BrowserGateway

from .selectors import ARTICLE_LIKE, ARTICLE_LIKE_ACTIVE


async def inspect_like_state(
    article: SourceArticleCandidate,
    browser: BrowserGateway | None,
) -> MarkerInspection:
    if browser is None or getattr(browser, "ready", True) is False:
        return MarkerInspection(LikeState.UNKNOWN, "BROWSER_NOT_READY", "source_like_v1")
    try:
        page = await browser.open(article.canonical_url)
        return await inspect_like_state_on_page(page)
    except Exception as exc:
        return MarkerInspection(
            LikeState.UNKNOWN,
            f"MARKER_READ_FAILED:{type(exc).__name__}",
            "source_like_v1",
        )


async def inspect_like_state_on_page(page: Any) -> MarkerInspection:
    """Inspect the already opened page without navigation or writes."""
    try:
        await page.wait_for_selector(ARTICLE_LIKE, timeout=15_000)
        active_count = await page.locator(ARTICLE_LIKE_ACTIVE).count()
        if active_count > 0:
            return MarkerInspection(LikeState.LIKED, "DOM_ACTIVE_CLASS", "source_like_v1")
        button_count = await page.locator(ARTICLE_LIKE).count()
        if button_count == 1:
            return MarkerInspection(LikeState.UNLIKED, "DOM_BUTTON_INACTIVE", "source_like_v1")
        return MarkerInspection(LikeState.UNKNOWN, "DOM_BUTTON_AMBIGUOUS", "source_like_v1")
    except Exception as exc:  # Browser implementations translate this to safe unknown state.
        return MarkerInspection(
            LikeState.UNKNOWN,
            f"MARKER_READ_FAILED:{type(exc).__name__}",
            "source_like_v1",
        )
