"""Use the current opus like state as the official-participation marker.

The marker is read before the lottery panel is opened.  A successful official
participation is marked by one exact dynamic-like click and an active-class
readback.  Unknown marker state is never treated as unliked.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

ACTIVITY_LIKE_SELECTOR = ".side-toolbar__action.like"
ACTIVITY_LIKE_ACTIVE_SELECTOR = ".side-toolbar__action.like.is-active"
ACTIVITY_LIKE_SELECTORS = (
    ".content .sidebar-wrap .side-toolbar__action.like",
    ".bili-dyn-action.like",
    ACTIVITY_LIKE_SELECTOR,
)
ACTIVITY_LIKE_ACTIVE_SELECTORS = (
    ACTIVITY_LIKE_ACTIVE_SELECTOR,
    ".side-toolbar__action.like.active",
    '.side-toolbar__action.like[aria-pressed="true"]',
    '.side-toolbar__action.like[data-state="active"]',
    '.side-toolbar__action.like[data-liked="true"]',
    ".bili-dyn-action.like.is-active",
    ".bili-dyn-action.like.active",
    '.bili-dyn-action.like[aria-pressed="true"]',
    '.bili-dyn-action.like[data-state="active"]',
    '.bili-dyn-action.like[data-liked="true"]',
    '[data-like-state="liked"]',
    '[aria-label*="已点赞"]',
    '[aria-label*="取消点赞"]',
)
_POLL_ATTEMPTS = 30
_POLL_INTERVAL_MS = 500


class ActivityLikeMarkerState(StrEnum):
    LIKED = "liked"
    UNLIKED = "unliked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ActivityLikeMarkerResult:
    state: ActivityLikeMarkerState
    code: str
    message: str
    click_attempted: bool = False
    selector: str | None = None


class ActivityLikeMarkerPage(Protocol):
    async def wait_for_selector(self, selector: str, *, timeout: int) -> Any: ...

    def locator(self, selector: str) -> Any: ...

    async def wait_for_timeout(self, timeout: int) -> None: ...


async def inspect_activity_like_marker(
    page: ActivityLikeMarkerPage,
    *,
    timeout_ms: int,
) -> ActivityLikeMarkerResult:
    """Return liked/unliked only when the unique marker can be proven."""

    try:
        await page.wait_for_selector(ACTIVITY_LIKE_SELECTOR, timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - try newer layout selectors
        if not await _has_any_like_control(page):
            return _unknown(
                "OFFICIAL_ACTIVITY_LIKE_READ_UNKNOWN",
                f"official activity like marker could not be loaded: {type(exc).__name__}",
            )
    return await _read_marker_counts(page)


async def ensure_activity_like_marker(
    page: ActivityLikeMarkerPage,
    *,
    timeout_ms: int,
) -> ActivityLikeMarkerResult:
    """Click the unique unliked marker once and require an active readback."""

    current = await inspect_activity_like_marker(page, timeout_ms=timeout_ms)
    if current.state is not ActivityLikeMarkerState.UNLIKED:
        return current

    try:
        like_button = page.locator(current.selector or ACTIVITY_LIKE_SELECTOR)
        # Do not force a coordinate click through a modal overlay.  The caller
        # must first expose the outer toolbar so Playwright can verify that the
        # actual like control receives the click.
        await like_button.click(timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - the click outcome is uncertain
        return _unknown(
            "OFFICIAL_ACTIVITY_LIKE_CLICK_UNKNOWN",
            f"official activity like click result is unknown: {type(exc).__name__}",
            click_attempted=True,
        )

    for attempt in range(_POLL_ATTEMPTS):
        marker = await _read_marker_counts(page, click_attempted=True)
        if marker.state is ActivityLikeMarkerState.LIKED:
            return ActivityLikeMarkerResult(
                ActivityLikeMarkerState.LIKED,
                "OFFICIAL_ACTIVITY_LIKE_CONFIRMED",
                "official activity like marker is active after one click",
                click_attempted=True,
            )
        if marker.state is ActivityLikeMarkerState.UNKNOWN:
            return marker
        if attempt + 1 < _POLL_ATTEMPTS:
            try:
                await page.wait_for_timeout(_POLL_INTERVAL_MS)
            except Exception:
                pass
    return _unknown(
        "OFFICIAL_ACTIVITY_LIKE_TERMINAL_UNKNOWN",
        "official activity like marker did not become active after one click",
        click_attempted=True,
    )


async def _read_marker_counts(
    page: ActivityLikeMarkerPage,
    *,
    click_attempted: bool = False,
) -> ActivityLikeMarkerResult:
    try:
        like_count, like_selector = await _read_unique_like_control(page)
        active_counts: list[int] = []
        for selector in ACTIVITY_LIKE_ACTIVE_SELECTORS:
            try:
                active_counts.append(int(await page.locator(selector).count()))
            except Exception:
                # Older page adapters may reject selectors from newer layout
                # variants; an unsupported selector is not itself an
                # ambiguous active marker.
                continue
    except Exception as exc:  # noqa: BLE001 - ambiguous page state must stop
        return _unknown(
            "OFFICIAL_ACTIVITY_LIKE_READ_UNKNOWN",
            f"official activity like marker could not be read: {type(exc).__name__}",
            click_attempted=click_attempted,
        )
    if like_count == 0:
        return _unknown(
            "OFFICIAL_ACTIVITY_LIKE_READ_UNKNOWN",
            "official activity like marker could not be found",
            click_attempted=click_attempted,
        )
    if like_count != 1:
        return _unknown(
            "OFFICIAL_ACTIVITY_LIKE_MARKER_AMBIGUOUS",
            f"expected one official activity like marker, found {like_count}",
            click_attempted=click_attempted,
        )
    if any(count > 1 for count in active_counts):
        return _unknown(
            "OFFICIAL_ACTIVITY_LIKE_MARKER_AMBIGUOUS",
            "more than one active official activity like marker was found",
            click_attempted=click_attempted,
        )
    active_count = 1 if any(count == 1 for count in active_counts) else 0
    if active_count == 1:
        return ActivityLikeMarkerResult(
            ActivityLikeMarkerState.LIKED,
            "OFFICIAL_ACTIVITY_ALREADY_LIKED",
            "official activity like marker is active",
            click_attempted=click_attempted,
            selector=like_selector,
        )
    if active_count == 0:
        return ActivityLikeMarkerResult(
            ActivityLikeMarkerState.UNLIKED,
            "OFFICIAL_ACTIVITY_NOT_LIKED",
            "official activity like marker is not active",
            click_attempted=click_attempted,
            selector=like_selector,
        )
    return _unknown(
        "OFFICIAL_ACTIVITY_LIKE_MARKER_AMBIGUOUS",
        f"expected at most one active official activity like marker, found {active_count}",
        click_attempted=click_attempted,
    )


def _unknown(
    code: str,
    message: str,
    *,
    click_attempted: bool = False,
    selector: str | None = None,
) -> ActivityLikeMarkerResult:
    return ActivityLikeMarkerResult(
        ActivityLikeMarkerState.UNKNOWN,
        code,
        message,
        click_attempted=click_attempted,
        selector=selector,
    )


async def _has_any_like_control(page: ActivityLikeMarkerPage) -> bool:
    for selector in ACTIVITY_LIKE_SELECTORS:
        try:
            if int(await page.locator(selector).count()) > 0:
                return True
        except Exception:
            continue
    return False


async def _read_unique_like_control(page: ActivityLikeMarkerPage) -> tuple[int, str | None]:
    for selector in ACTIVITY_LIKE_SELECTORS:
        try:
            count = int(await page.locator(selector).count())
        except Exception:
            continue
        if count > 0:
            return count, selector
    return 0, None
