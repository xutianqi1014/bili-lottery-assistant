"""Read-only DOM evidence for one currently executing non-official dynamic.

This module never clicks, scrolls, fills, or submits anything.  It exists so
classification and requirement parsing can use the dynamic's own body rather
than the navigation bar or hundreds of other users' comments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

UNOFFICIAL_SELECTOR_VERSION = "unofficial_page_evidence_v2-author-header"

_OUTER_BODY_SELECTORS = (
    '.bili-dyn-content__forw__desc[data-orig="0"]',
    ".opus-module-content",
    '.bili-dyn-content [data-module="desc"][data-orig="0"]',
)
_FORWARDED_ORIGINAL_SELECTOR = ".bili-dyn-content__orig.reference"
_COMMENT_EDITOR_SELECTORS = (
    "bili-comments bili-comment-box bili-comment-rich-textarea .brt-editor",
    "bili-comment-rich-textarea .brt-editor",
    'bili-comments [contenteditable="true"]',
)
_COMMENT_PUBLISH_SELECTORS = (
    "bili-comments bili-comment-box button",
    "bili-comment-box button",
)
_COMMENT_REPOST_SELECTORS = (
    "bili-comments bili-comment-box bili-checkbox",
    "bili-comment-box bili-checkbox",
)
AUTHOR_NAME_SELECTORS = (
    ".opus-module-author__name",
    ".bili-dyn-item__author",
    ".bili-dyn-item__author-name",
    '.bili-dyn-item__header .bili-dyn-title__text',
)


@dataclass(frozen=True, slots=True)
class UnofficialPageEvidence:
    outer_text: str = ""
    forwarded_original_text: str = ""
    has_forwarded_original: bool = False
    comment_editor_present: bool = False
    comment_publish_present: bool = False
    comment_repost_control_present: bool = False
    author_name: str = ""
    evidence_codes: tuple[str, ...] = ()
    selector_version: str = UNOFFICIAL_SELECTOR_VERSION


async def read_unofficial_page_evidence(page: object) -> UnofficialPageEvidence:
    """Collect stable, non-mutating evidence from a Playwright-like page."""

    outer_selector, outer_text = await _first_text(page, _OUTER_BODY_SELECTORS)
    original_count = await _count(page, _FORWARDED_ORIGINAL_SELECTOR)
    original_text = (
        await _locator_text(page, _FORWARDED_ORIGINAL_SELECTOR) if original_count else ""
    )
    comment_editor_present = await _any_count(page, _COMMENT_EDITOR_SELECTORS)
    comment_publish_present = await _has_button_text(page, _COMMENT_PUBLISH_SELECTORS, "发布")
    comment_repost_control_present = await _any_count(page, _COMMENT_REPOST_SELECTORS)
    author_name = await _first_text_value(page, AUTHOR_NAME_SELECTORS)

    evidence_codes: list[str] = []
    if outer_selector:
        evidence_codes.append("UNOFFICIAL_SCOPED_BODY_FOUND")
    if original_count:
        evidence_codes.append("UNOFFICIAL_FORWARDED_ORIGINAL_FOUND")
    if comment_editor_present:
        evidence_codes.append("UNOFFICIAL_COMMENT_EDITOR_FOUND")
    if comment_publish_present:
        evidence_codes.append("UNOFFICIAL_COMMENT_PUBLISH_FOUND")
    if comment_repost_control_present:
        evidence_codes.append("UNOFFICIAL_COMMENT_REPOST_CONTROL_FOUND")

    return UnofficialPageEvidence(
        outer_text=_clean_text(outer_text),
        forwarded_original_text=_clean_text(original_text),
        has_forwarded_original=bool(original_count),
        comment_editor_present=comment_editor_present,
        comment_publish_present=comment_publish_present,
        comment_repost_control_present=comment_repost_control_present,
        author_name=_clean_text(author_name),
        evidence_codes=tuple(evidence_codes),
    )


async def _first_text(page: object, selectors: tuple[str, ...]) -> tuple[str | None, str]:
    for selector in selectors:
        if await _count(page, selector):
            return selector, await _locator_text(page, selector)
    return None, ""


async def _any_count(page: object, selectors: tuple[str, ...]) -> bool:
    for selector in selectors:
        if await _count(page, selector):
            return True
    return False


async def _has_button_text(
    page: object,
    selectors: tuple[str, ...],
    expected_text: str,
) -> bool:
    for selector in selectors:
        locator = _locator(page, selector)
        if locator is None:
            continue
        try:
            count = await locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                text = _clean_text(str(await candidate.inner_text(timeout=1_000)))
                if text == expected_text:
                    return True
        except Exception:
            continue
    return False


async def _count(page: object, selector: str) -> int:
    locator = _locator(page, selector)
    if locator is None:
        return 0
    try:
        count = getattr(locator, "count", None)
        return int(await count()) if callable(count) else 0
    except Exception:
        return 0


async def _locator_text(page: object, selector: str) -> str:
    locator = _locator(page, selector)
    if locator is None:
        return ""
    try:
        first: Any = getattr(locator, "first", locator)
        inner_text = getattr(first, "inner_text", None)
        return str(await inner_text(timeout=1_000)) if callable(inner_text) else ""
    except Exception:
        return ""


async def _first_text_value(page: object, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        value = await _locator_text(page, selector)
        if value:
            return value
    return ""


def _locator(page: object, selector: str) -> Any | None:
    factory = getattr(page, "locator", None)
    if not callable(factory):
        return None
    try:
        return factory(selector)
    except Exception:
        return None


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\u200b", "").replace("\ufeff", "").split())
