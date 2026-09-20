"""Read-only author follow-state inspection for activity execution.

The reservation flow needs to report whether the dynamic author is already
followed, but it must not infer that state from the reservation button and it
must not click the follow control as a side effect.  This module resolves the
author profile from the current dynamic (falling back to the exact-name search
page when necessary) and reads one visible ``.space-follow-btn`` control.
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import quote, urlsplit

from backend.activity_engine.shared.author_location import (
    AuthorIdentityPolicy,
    author_profile_ids,
)
from backend.activity_engine.shared.dom_read import (
    first_text as _first_text,
)
from backend.activity_engine.shared.dom_read import (
    inner_text as _inner_text,
)
from backend.activity_engine.shared.dom_read import (
    normalize as _normalize,
)
from backend.activity_engine.shared.dom_read import (
    page_text as _page_text,
)
from backend.activity_engine.shared.dom_read import (
    poll_read,
    wait_for_unique_candidates,
)
from backend.activity_engine.unofficial.page_evidence import AUTHOR_NAME_SELECTORS

PROFILE_FOLLOW_SELECTOR = ".space-follow-btn"
AUTHOR_PROFILE_SELECTOR = 'a[href*="space.bilibili.com/"]'
_FOLLOW_DONE_MARKERS = ("已关注", "互相关注")
_FOLLOW_READY_MARKER = "关注"
_AUTHOR_SEARCH_DELAY_MIN_SEC = 1.0
_AUTHOR_SEARCH_DELAY_MAX_SEC = 2.0
_PROFILE_ID_RE = re.compile(r"^/space/(\d+)/?$", re.IGNORECASE)


class AuthorFollowState(StrEnum):
    FOLLOWING = "following"
    NOT_FOLLOWING = "not_following"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AuthorFollowInspection:
    state: AuthorFollowState
    code: str
    message: str
    profile_url: str | None = None


async def inspect_author_follow(
    browser: Any,
    dynamic_page: Any,
    *,
    timeout_ms: int = 15_000,
    poll_attempts: int = 6,
    poll_interval_ms: int = 500,
) -> AuthorFollowInspection:
    """Read the exact author profile follow marker without clicking it."""
    resolved = await _resolve_author_follow_control(
        browser,
        dynamic_page,
        timeout_ms=timeout_ms,
        poll_attempts=poll_attempts,
        poll_interval_ms=poll_interval_ms,
    )
    if isinstance(resolved, AuthorFollowInspection):
        return resolved
    profile_page, button, profile_url = resolved
    return await _read_follow_state(profile_page, button, profile_url)


async def ensure_author_follow(
    browser: Any,
    dynamic_page: Any,
    *,
    timeout_ms: int = 15_000,
    poll_attempts: int = 30,
    poll_interval_ms: int = 500,
) -> AuthorFollowInspection:
    """Check the author profile and follow it once when it is not followed."""

    resolved = await _resolve_author_follow_control(
        browser,
        dynamic_page,
        timeout_ms=timeout_ms,
        poll_attempts=min(6, max(1, poll_attempts)),
        poll_interval_ms=poll_interval_ms,
    )
    if isinstance(resolved, AuthorFollowInspection):
        return resolved
    profile_page, button, profile_url = resolved
    current = await _read_follow_state(profile_page, button, profile_url)
    if current.state is AuthorFollowState.FOLLOWING:
        return current
    if current.state is AuthorFollowState.UNKNOWN:
        return current
    try:
        enabled = getattr(button, "is_enabled", None)
        if callable(enabled) and not await enabled():
            return _unknown(
                "FOLLOW_CONTROL_DISABLED",
                "profile follow control is disabled",
                profile_url=profile_url,
            )
        scroll = getattr(button, "scroll_into_view_if_needed", None)
        if callable(scroll):
            await scroll(timeout=timeout_ms)
        click = getattr(button, "click", None)
        if not callable(click):
            return _unknown(
                "FOLLOW_CLICK_UNKNOWN",
                "profile follow control cannot be clicked",
                profile_url=profile_url,
            )
        await click(timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - click outcome is uncertain
        return _unknown(
            "FOLLOW_CLICK_UNKNOWN",
            f"follow click result is unknown ({type(exc).__name__})",
            profile_url=profile_url,
        )

    for attempt in range(max(1, poll_attempts)):
        terminal = await _read_follow_state(profile_page, button, profile_url)
        if terminal.state is AuthorFollowState.FOLLOWING:
            return AuthorFollowInspection(
                AuthorFollowState.FOLLOWING,
                "FOLLOW_CONFIRMED",
                "profile follow button now shows followed",
                profile_url,
            )
        if terminal.state is AuthorFollowState.UNKNOWN:
            return terminal
        if attempt + 1 < poll_attempts:
            await _wait_for_timeout(profile_page, poll_interval_ms)
    return _unknown(
        "FOLLOW_TERMINAL_UNKNOWN",
        "follow marker did not become active after one click",
        profile_url=profile_url,
    )


async def _resolve_author_follow_control(
    browser: Any,
    dynamic_page: Any,
    *,
    timeout_ms: int,
    poll_attempts: int,
    poll_interval_ms: int,
) -> tuple[Any, Any, str] | AuthorFollowInspection:
    try:
        author = await _wait_for_author_name(
            dynamic_page,
            poll_attempts=poll_attempts,
            poll_interval_ms=poll_interval_ms,
        )
        if not author:
            return _unknown("FOLLOW_AUTHOR_NOT_FOUND", "dynamic author name was not found")

        profile_ids = await _wait_for_author_profile_ids(
            dynamic_page,
            author,
            poll_attempts=poll_attempts,
            poll_interval_ms=poll_interval_ms,
        )
        if len(profile_ids) == 1:
            profile_id = next(iter(profile_ids))
        elif profile_ids:
            return _unknown(
                "FOLLOW_PROFILE_NOT_UNIQUE",
                "exactly one direct author profile was found",
            )
        else:
            resolved_profile_id = await _resolve_profile_id_from_search(
                browser,
                author,
                timeout_ms=timeout_ms,
            )
            if resolved_profile_id is None:
                return _unknown(
                    "FOLLOW_PROFILE_NOT_UNIQUE",
                    "exactly one exact author profile was found",
                )
            profile_id = resolved_profile_id

        profile_url = "https://space.bilibili.com/" + profile_id
        profile_page = await browser.open(profile_url)
        buttons = await _wait_for_unique_candidates(
            profile_page,
            PROFILE_FOLLOW_SELECTOR,
            poll_attempts=poll_attempts,
            poll_interval_ms=poll_interval_ms,
        )
        if len(buttons) != 1:
            return _unknown(
                "FOLLOW_CONTROL_NOT_UNIQUE",
                "exactly one visible profile follow button is required",
                profile_url=profile_url,
            )
        return profile_page, buttons[0], profile_url
    except Exception as exc:  # noqa: BLE001 - read state is not trustworthy
        return _unknown(
            "FOLLOW_CHECK_UNKNOWN",
            f"author follow status could not be read ({type(exc).__name__})",
        )


async def _read_follow_state(
    profile_page: Any,
    button: Any,
    profile_url: str,
) -> AuthorFollowInspection:
    status = _normalize(await _inner_text(button))
    page_text = await _page_text(profile_page)
    if any(marker in status or marker in page_text for marker in _FOLLOW_DONE_MARKERS):
        return AuthorFollowInspection(
            AuthorFollowState.FOLLOWING,
            "FOLLOW_ALREADY_DONE",
            "author profile already shows followed",
            profile_url,
        )
    if status == _FOLLOW_READY_MARKER:
        return AuthorFollowInspection(
            AuthorFollowState.NOT_FOLLOWING,
            "FOLLOW_NOT_DONE",
            "author profile follow control shows 关注",
            profile_url,
        )
    return _unknown(
        "FOLLOW_STATUS_UNRECOGNIZED",
        "profile follow status was not recognized",
        profile_url=profile_url,
    )


async def _resolve_profile_id_from_search(
    browser: Any,
    author: str,
    *,
    timeout_ms: int,
) -> str | None:
    search_url = "https://search.bilibili.com/upuser?keyword=" + quote(author)
    search_page = await browser.open(search_url)
    await _wait_random_delay(
        search_page,
        _AUTHOR_SEARCH_DELAY_MIN_SEC,
        _AUTHOR_SEARCH_DELAY_MAX_SEC,
    )
    matches = await _author_profile_ids(search_page, author)
    return next(iter(matches)) if len(matches) == 1 else None


async def _wait_for_author_name(page: Any, *, poll_attempts: int, poll_interval_ms: int) -> str:
    return await poll_read(
        page,
        lambda: _first_text(page, AUTHOR_NAME_SELECTORS),
        bool,
        poll_attempts=poll_attempts,
        poll_interval_ms=poll_interval_ms,
        wait=_wait_for_timeout,
    )


async def _wait_for_author_profile_ids(
    page: Any,
    author: str,
    *,
    poll_attempts: int,
    poll_interval_ms: int,
) -> set[str]:
    return await poll_read(
        page,
        lambda: _author_profile_ids(page, author),
        bool,
        poll_attempts=poll_attempts,
        poll_interval_ms=poll_interval_ms,
        wait=_wait_for_timeout,
    )


async def _wait_for_unique_candidates(
    page: Any,
    selector: str,
    *,
    poll_attempts: int,
    poll_interval_ms: int,
) -> list[Any]:
    return await wait_for_unique_candidates(
        page,
        selector,
        poll_attempts=poll_attempts,
        poll_interval_ms=poll_interval_ms,
        wait=_wait_for_timeout,
    )


async def _author_profile_ids(page: Any, author: str) -> set[str]:
    return await author_profile_ids(
        page,
        author,
        selector=AUTHOR_PROFILE_SELECTOR,
        policy=AuthorIdentityPolicy(_author_name_matches, _profile_id_from_href),
    )


def _author_name_matches(display_name: str, author: str) -> bool:
    return display_name.lstrip("@").strip() == author.lstrip("@").strip()


def _profile_id_from_href(href: str) -> str:
    parsed = urlsplit("https:" + href if href.startswith("//") else href)
    path = parsed.path.rstrip("/")
    parts = path.split("/")
    if len(parts) >= 2 and parts[-2].lower() == "space" and parts[-1].isdigit():
        return parts[-1]
    if len(parts) == 2 and parts[0] == "" and parts[1].isdigit():
        return parts[1]
    if _PROFILE_ID_RE.fullmatch(path):
        return _PROFILE_ID_RE.fullmatch(path).group(1)  # type: ignore[union-attr]
    return ""


async def _wait_for_timeout(page: Any, timeout_ms: int) -> None:
    wait = getattr(page, "wait_for_timeout", None)
    if callable(wait):
        try:
            await wait(timeout_ms)
            return
        except Exception:
            pass
    await asyncio.sleep(max(0, timeout_ms) / 1000)


async def _wait_random_delay(page: Any, minimum_sec: float, maximum_sec: float) -> None:
    delay_sec = random.uniform(max(0.0, minimum_sec), max(minimum_sec, maximum_sec))
    await _wait_for_timeout(page, int(round(delay_sec * 1000)))


def _unknown(code: str, message: str, *, profile_url: str | None = None) -> AuthorFollowInspection:
    return AuthorFollowInspection(AuthorFollowState.UNKNOWN, code, message, profile_url)


__all__ = [
    "AUTHOR_PROFILE_SELECTOR",
    "AuthorFollowInspection",
    "AuthorFollowState",
    "PROFILE_FOLLOW_SELECTOR",
    "ensure_author_follow",
    "inspect_author_follow",
]
