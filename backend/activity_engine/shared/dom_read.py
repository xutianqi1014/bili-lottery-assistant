"""Read-only DOM primitives shared by activity transports.

Adapter fallbacks and exception boundaries intentionally match existing readers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


def normalize(value: str) -> str:
    return " ".join(value.replace("\u200b", "").replace("\ufeff", "").split())


async def inner_text(locator: Any) -> str:
    method = getattr(locator, "inner_text", None)
    if not callable(method):
        return ""
    try:
        return str(await method(timeout=2_000))
    except TypeError:
        return str(await method())
    except Exception:
        return ""


async def attribute(locator: Any, name: str) -> str:
    method = getattr(locator, "get_attribute", None)
    if not callable(method):
        return ""
    try:
        return str(await method(name) or "")
    except Exception:
        return ""


async def visible_candidates(page: Any, selector: str, *, text: str | None = None) -> list[Any]:
    locator_factory = getattr(page, "locator", None)
    if not callable(locator_factory):
        return []
    locator = locator_factory(selector)
    count_fn = getattr(locator, "count", None)
    if not callable(count_fn):
        return []
    try:
        count = int(await count_fn())
    except Exception:
        return []
    result: list[Any] = []
    for index in range(count):
        candidate = locator.nth(index)
        try:
            visible = (
                await candidate.is_visible()
                if callable(getattr(candidate, "is_visible", None))
                else True
            )
        except Exception:
            visible = False
        if not visible:
            continue
        if text is not None and normalize(await inner_text(candidate)) != text:
            continue
        result.append(candidate)
    return result


async def first_text(page: Any, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        values = await visible_candidates(page, selector)
        if values:
            value = normalize(await inner_text(values[0]))
            if value:
                return value
    return ""


async def page_text(page: Any) -> str:
    locator_factory = getattr(page, "locator", None)
    if not callable(locator_factory):
        return ""
    try:
        return normalize(await inner_text(locator_factory("body")))
    except Exception:
        return ""


Wait = Callable[[Any, int], Awaitable[None]]


async def browser_wait(page: Any, timeout_ms: int) -> None:
    """Best-effort browser wait; unofficial polling has no sleep fallback."""
    wait = getattr(page, "wait_for_timeout", None)
    if callable(wait):
        try:
            await wait(timeout_ms)
        except Exception:
            pass


async def poll_read[T](
    page: Any,
    read: Callable[[], Awaitable[T]],
    accept: Callable[[T], bool],
    *,
    poll_attempts: int,
    poll_interval_ms: int,
    wait: Wait,
) -> T:
    """Poll read-only evidence; preserve the last ambiguous result on exhaustion.

    Read exceptions propagate to the caller's existing unknown-result boundary.
    The caller supplies its delay policy and polling budget.
    """
    for attempt in range(max(1, poll_attempts)):
        latest = await read()
        if accept(latest):
            return latest
        if attempt + 1 < poll_attempts:
            await wait(page, poll_interval_ms)
    return latest


async def wait_for_unique_candidates(
    page: Any,
    selector: str,
    *,
    poll_attempts: int,
    poll_interval_ms: int,
    wait: Wait,
    text: str | None = None,
) -> list[Any]:
    return await poll_read(
        page,
        lambda: visible_candidates(page, selector, text=text),
        lambda candidates: len(candidates) == 1,
        poll_attempts=poll_attempts,
        poll_interval_ms=poll_interval_ms,
        wait=wait,
    )
