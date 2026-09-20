"""Read-only extraction of dynamic links from a source article."""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from typing import Any

from backend.domain.entities import (
    ActivityExtractionResult,
    ActivityExtractionStats,
    ActivityRef,
    SourceArticleCandidate,
)
from backend.domain.ports import BrowserGateway

from .html_parser import find_content_root, parse_html
from .queue_rules import collect_queue


def content_fingerprint(text: str) -> str:
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def extract_activities(
    article: SourceArticleCandidate,
    browser: BrowserGateway | None,
    *,
    include_sections: Collection[str] | None = None,
    excluded_sections: Collection[str] | None = None,
) -> ActivityExtractionResult:
    if browser is None:
        return ActivityExtractionResult(
            status="browser_not_ready",
            reason_code="BROWSER_NOT_READY",
            safe_detail="来源专栏解析需要已登录的可见浏览器。",
        )
    try:
        page = await browser.open(article.canonical_url)
    except Exception as exc:
        return ActivityExtractionResult(
            status="failed",
            reason_code="SOURCE_ARTICLE_NAVIGATION_FAILED",
            safe_detail=f"来源专栏无法打开：{type(exc).__name__}。",
        )
    return await extract_activities_on_page(
        article, page, include_sections=include_sections, excluded_sections=excluded_sections
    )


async def extract_activities_on_page(
    article: SourceArticleCandidate,
    page: Any,
    *,
    include_sections: Collection[str] | None = None,
    excluded_sections: Collection[str] | None = None,
) -> ActivityExtractionResult:
    """Extract read-only evidence from the page used for marker inspection."""
    try:
        html = await page.content()
    except Exception as exc:
        return ActivityExtractionResult(
            status="failed",
            reason_code="SOURCE_ARTICLE_NAVIGATION_FAILED",
            safe_detail=f"来源专栏无法打开：{type(exc).__name__}。",
        )

    document = parse_html(html)
    root = find_content_root(document)
    if root is None:
        return ActivityExtractionResult(
            status="failed",
            reason_code="SOURCE_CONTENT_NOT_FOUND",
            safe_detail="未找到来源专栏正文容器，未猜测动态队列。",
        )

    queue = collect_queue(
        root,
        article.canonical_url,
        include_sections=include_sections,
        excluded_sections=excluded_sections,
    )
    refs = tuple(
        ActivityRef(
            dynamic_id=item.dynamic_id,
            canonical_url=item.canonical_url,
            source_position=item.source_position,
            title=item.title,
            source_section=item.source_section,
        )
        for item in queue.items
    )
    stats = ActivityExtractionStats(
        aggregate_excluded=queue.stats.aggregate_excluded,
        started_after_pinned=queue.stats.started_after_pinned,
        start_mode=queue.stats.start_mode,
        links_seen=queue.stats.links_seen,
        unique_links=queue.stats.unique_links,
        content_fingerprint=content_fingerprint(root.text_content()),
    )
    if not refs:
        return ActivityExtractionResult(
            refs=refs,
            stats=stats,
            status="empty",
            reason_code="SOURCE_EMPTY_AFTER_PARSE",
            safe_detail="来源专栏未解析出可处理的动态链接，本轮不标记来源专栏。",
        )
    return ActivityExtractionResult(refs=refs, stats=stats)


async def extract_activity_refs(
    article: SourceArticleCandidate,
    browser: BrowserGateway | None,
) -> list[ActivityRef]:
    """Compatibility helper for callers that only need the links."""

    result = await extract_activities(article, browser)
    return list(result.refs)
