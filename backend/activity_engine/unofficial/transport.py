"""DOM writer for non-official Bilibili giveaway actions.

The transport is deliberately small and browser-only.  It never calls a
private Bilibili write API: every mutation is performed through the same
visible controls a user would use.  Like, repost and follow clicks are followed
by a terminal state check.  Comment publishing is the deliberate exception:
once the unique publish button click completes without an exception, the submit
is accepted because Bilibili may render a newly posted comment asynchronously.
A click whose result cannot be accepted or proven is returned as UNKNOWN;
callers must not retry it automatically.
"""

from __future__ import annotations

import asyncio
import inspect
import random
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlsplit

from .actions import (
    InvalidWriteTargetError,
    UnofficialAction,
    WriteOperationResult,
    WriteOutcomeState,
    _validate_dynamic_target,
)
from .page_evidence import AUTHOR_NAME_SELECTORS

UNOFFICIAL_WRITE_SELECTOR_VERSION = (
    "unofficial_write_dom_v9-comment-repost-hydration-scoped-like-author-header"
)

LIKE_SELECTOR = ".side-toolbar__action.like"
# On a forwarded dynamic Bilibili can briefly render more than one toolbar
# with the same generic like class (the outer dynamic and a hydrated copy of
# the forwarded card).  The current page layout puts the actionable outer
# toolbar below ``.content > .sidebar-wrap``.  Prefer this structural scope;
# retain the generic selector as a compatibility fallback for older layouts
# and the lightweight test/browser adapters.
LIKE_SCOPED_SELECTOR = (
    ".content > .sidebar-wrap > .side-toolbar > .side-toolbar__box "
    "> .side-toolbar__action.like"
)
LIKE_CONTENT_SCOPED_SELECTOR = ".content .sidebar-wrap .side-toolbar__action.like"
LIKE_ACTIVE_SELECTOR = ".side-toolbar__action.like.is-active"
LIKE_ACTIVE_SELECTORS = (
    f"{LIKE_SCOPED_SELECTOR}.is-active",
    f"{LIKE_SCOPED_SELECTOR}.active",
    f'{LIKE_SCOPED_SELECTOR}[aria-pressed="true"]',
    f'{LIKE_SCOPED_SELECTOR}[data-state="active"]',
    f'{LIKE_SCOPED_SELECTOR}[data-liked="true"]',
    f'{LIKE_SCOPED_SELECTOR}[class*="liked"]',
    LIKE_ACTIVE_SELECTOR,
    ".side-toolbar__action.like.active",
    '.side-toolbar__action.like[aria-pressed="true"]',
    '.side-toolbar__action.like[data-state="active"]',
    '.side-toolbar__action.like[data-liked="true"]',
    '.side-toolbar__action.like[class*="liked"]',
    ".bili-dyn-action.like.is-active",
    ".bili-dyn-action.like.active",
    '.bili-dyn-action.like[aria-pressed="true"]',
    '.bili-dyn-action.like[data-state="active"]',
    '.bili-dyn-action.like[data-liked="true"]',
    '[data-like-state="liked"]',
    '[aria-label*="已点赞"]',
    '[aria-label*="取消点赞"]',
    '[title*="已点赞"]',
    '[title*="取消点赞"]',
)
FORWARD_SELECTOR = ".side-toolbar__action.forward"
COMMENT_EDITOR_SELECTOR = (
    'bili-comments bili-comment-box bili-comment-rich-textarea '
    '.brt-editor[contenteditable="true"]'
)
COMMENT_PUBLISH_SELECTOR = "bili-comments bili-comment-box button"
COMMENT_REPOST_SELECTOR = 'bili-comments bili-comment-box bili-checkbox[value="sync"]'
SHARE_SELECTOR = ".bili-dyn-share__wrap"
SHARE_EDITOR_SELECTOR = ".bili-rich-textarea__inner"
SHARE_PUBLISH_SELECTOR = ".bili-dyn-share-publishing__action.launcher"
SHARE_CLOSE_SELECTOR = ".bili-dyn-share-publishing__close"
PROFILE_FOLLOW_SELECTOR = ".space-follow-btn"
AUTHOR_PROFILE_SELECTOR = 'a[href*="space.bilibili.com/"]'

_SUCCESS_MARKERS = (
    "评论成功",
    "发布成功",
    "转发成功",
    "动态发布成功",
    "已转发",
)
# Keep this list limited to explicit verification/challenge signals.  A dynamic
# can legitimately mention “登录” (for example, a shop being logged in on
# several platforms); treating that ordinary content as a security challenge
# would block the first comment before any write occurs.
_SECURITY_MARKERS = ("验证码", "安全验证", "风险验证")
_FOLLOW_DONE_MARKERS = ("已关注", "互相关注")
_FOLLOW_READY_MARKER = "关注"
_AUTHOR_SEARCH_DELAY_MIN_SEC = 1.0
_AUTHOR_SEARCH_DELAY_MAX_SEC = 2.0
_ID_RE = re.compile(r"^/opus/(\d+)/?$", re.IGNORECASE)
_DYNAMIC_RE = re.compile(r"^/(\d+)/?$")


class DomUnofficialTransport:
    """Perform one idempotent-aware non-official action through the DOM."""

    selector_version = UNOFFICIAL_WRITE_SELECTOR_VERSION

    def __init__(self, browser: Any, *, poll_attempts: int = 30, poll_interval_ms: int = 500):
        self.browser = browser
        self.poll_attempts = max(1, poll_attempts)
        self.poll_interval_ms = max(0, poll_interval_ms)

    async def perform(
        self,
        action: UnofficialAction,
        *,
        target_url: str,
        payload: Mapping[str, object],
    ) -> WriteOperationResult:
        try:
            _validate_dynamic_target(target_url)
        except InvalidWriteTargetError:
            return _failed("WRITE_TARGET_INVALID", "target is not an allowed Bilibili dynamic")

        try:
            if action is UnofficialAction.FOLLOW:
                return await self._follow(target_url)
            page = await self.browser.open(target_url)
            if action is UnofficialAction.LIKE:
                return await self._like(page)
            if action is UnofficialAction.COMMENT:
                return await self._comment(page, payload)
            if action is UnofficialAction.REPOST:
                return await self._repost(page, payload)
            return _failed("UNSUPPORTED_UNOFFICIAL_ACTION", action.value)
        except Exception as exc:  # a post-click exception is intentionally unknown
            return _unknown(
                "WRITE_RESULT_UNKNOWN",
                f"browser operation returned an unknown result ({type(exc).__name__})",
            )

    async def _like(self, page: Any) -> WriteOperationResult:
        if await _visible_count_any(page, LIKE_ACTIVE_SELECTORS):
            return _already("DYNAMIC_ALREADY_LIKED", "dynamic like is already active")
        controls = await self._wait_for_unique_like_candidates(page)
        if len(controls) != 1:
            return _failed(
                "DYNAMIC_LIKE_CONTROL_NOT_UNIQUE",
                "exactly one visible outer dynamic like control is required",
            )
        if await _security_page(page):
            return _unknown(
                "DYNAMIC_LIKE_SECURITY_CHALLENGE", "verification or security challenge is visible"
            )
        try:
            await _click(controls[0])
        except Exception as exc:
            return _unknown(
                "DYNAMIC_LIKE_CLICK_UNKNOWN", f"like click result is unknown ({type(exc).__name__})"
            )
        if await self._wait_for(page, lambda: _visible_count_any(page, LIKE_ACTIVE_SELECTORS)):
            return _success("DYNAMIC_LIKE_CONFIRMED", "dynamic like is active")
        return _unknown(
            "DYNAMIC_LIKE_TERMINAL_UNKNOWN", "like marker did not become active after one click"
        )

    async def _comment(self, page: Any, payload: Mapping[str, object]) -> WriteOperationResult:
        text = str(payload.get("commentText", "")).strip()
        if not text:
            return _failed("COMMENT_TEXT_EMPTY", "a deterministic comment is required")
        editors = await self._wait_for_unique_candidates(page, COMMENT_EDITOR_SELECTOR)
        if len(editors) != 1:
            return _failed(
                "COMMENT_EDITOR_NOT_UNIQUE", "exactly one visible comment editor is required"
            )
        if await _security_page(page):
            return _unknown(
                "COMMENT_SECURITY_CHALLENGE", "verification or security challenge is visible"
            )
        try:
            await _fill(editors[0], text)
        except Exception as exc:
            return _unknown(
                "COMMENT_FILL_UNKNOWN",
                f"comment editor fill result is unknown ({type(exc).__name__})",
            )

        repost_checked = False
        if bool(payload.get("repostWithComment")):
            # The comment component can briefly expose the old and hydrated
            # sync-to-dynamic checkbox at the same time.  Querying only once
            # made the current build fail with COMMENT_REPOST_CONTROL_NOT_UNIQUE
            # even though one visible checkbox remained after hydration.
            controls = await self._wait_for_unique_candidates(page, COMMENT_REPOST_SELECTOR)
            if len(controls) != 1:
                return _failed(
                    "COMMENT_REPOST_CONTROL_NOT_UNIQUE",
                    "the sync-to-dynamic checkbox was not uniquely found",
                )
            repost_checked = await _is_checked(controls[0])
            if not repost_checked:
                try:
                    await _click(controls[0])
                except Exception as exc:
                    return _unknown(
                        "COMMENT_REPOST_CHECK_UNKNOWN",
                        f"repost checkbox result is unknown ({type(exc).__name__})",
                    )
                repost_checked = await self._wait_for(page, lambda: _checked(controls[0]))
                if not repost_checked:
                    return _unknown(
                        "COMMENT_REPOST_CHECK_TERMINAL_UNKNOWN",
                        "repost checkbox did not become checked",
                    )

        buttons = await _visible_candidates(page, COMMENT_PUBLISH_SELECTOR, text="发布")
        if len(buttons) != 1:
            return _failed(
                "COMMENT_PUBLISH_CONTROL_NOT_UNIQUE",
                "exactly one visible comment publish button is required",
            )
        try:
            await _click(buttons[0])
        except Exception as exc:
            return _unknown(
                "COMMENT_SUBMIT_UNKNOWN", f"comment submit result is unknown ({type(exc).__name__})"
            )
        return _success(
            "COMMENT_SUBMIT_ACCEPTED",
            "comment publish click completed; Bilibili may render the new comment asynchronously",
            confirmed_actions=("repost",) if repost_checked else (),
        )

    async def _repost(self, page: Any, payload: Mapping[str, object]) -> WriteOperationResult:
        controls = await _visible_candidates(page, FORWARD_SELECTOR)
        if len(controls) != 1:
            return _failed(
                "REPOST_CONTROL_NOT_UNIQUE", "exactly one visible forward control is required"
            )
        if await _security_page(page):
            return _unknown(
                "REPOST_SECURITY_CHALLENGE", "verification or security challenge is visible"
            )
        try:
            await _click(controls[0])
        except Exception as exc:
            return _unknown(
                "REPOST_CLICK_UNKNOWN", f"forward click result is unknown ({type(exc).__name__})"
            )
        if not await self._wait_for(page, lambda: _visible_count(page, SHARE_SELECTOR)):
            return _unknown(
                "REPOST_DIALOG_NOT_OPENED", "forward dialog did not open after one click"
            )
        editors = await _visible_candidates(page, SHARE_EDITOR_SELECTOR)
        if len(editors) != 1:
            return _failed(
                "REPOST_EDITOR_NOT_UNIQUE", "exactly one visible forward editor is required"
            )
        text = str(payload.get("commentText", "")).strip()
        if text:
            try:
                await _fill(editors[0], text)
            except Exception as exc:
                return _unknown(
                    "REPOST_FILL_UNKNOWN",
                    f"forward editor fill result is unknown ({type(exc).__name__})",
                )
        buttons = await _visible_candidates(page, SHARE_PUBLISH_SELECTOR)
        if len(buttons) != 1:
            return _failed(
                "REPOST_PUBLISH_CONTROL_NOT_UNIQUE",
                "exactly one visible forward publish control is required",
            )
        try:
            await _click(buttons[0])
        except Exception as exc:
            return _unknown(
                "REPOST_SUBMIT_UNKNOWN", f"forward submit result is unknown ({type(exc).__name__})"
            )
        confirmed = await self._wait_for(page, lambda: _share_terminal(page))
        if not confirmed:
            return _unknown(
                "REPOST_TERMINAL_UNKNOWN", "forward success was not confirmed after one publish"
            )
        return _success("REPOST_CONFIRMED", "forward dialog closed and success evidence was found")

    async def _follow(self, target_url: str) -> WriteOperationResult:
        page = await self.browser.open(target_url)
        author = await self._wait_for_author_name(page)
        if not author:
            return _failed("FOLLOW_AUTHOR_NOT_FOUND", "dynamic author name was not found")

        # New opus pages expose the author profile as a visible @mention link.
        # Prefer that link so the browser goes straight to the author's profile;
        # opening the user-search page first leaves the UI on a search result page
        # whenever the search result is still hydrating or is not unique.  Keep the
        # search flow as a compatibility fallback for older dynamic layouts that
        # do not expose a profile href in the author block.
        direct_profile_ids = await self._wait_for_author_profile_ids(page, author)
        if len(direct_profile_ids) == 1:
            profile_id = next(iter(direct_profile_ids))
        elif direct_profile_ids:
            return _failed(
                "FOLLOW_PROFILE_NOT_UNIQUE", "exactly one direct author profile was found"
            )
        else:
            search_url = "https://search.bilibili.com/upuser?keyword=" + quote(author)
            search_page = await self.browser.open(search_url)
            # The user-search page is a hydrated SPA. Give its result list a
            # human-like 1–2 second settling window before matching exact
            # author names; querying immediately can observe an empty list and
            # incorrectly produce FOLLOW_PROFILE_NOT_UNIQUE.
            await _wait_random_delay(
                search_page,
                _AUTHOR_SEARCH_DELAY_MIN_SEC,
                _AUTHOR_SEARCH_DELAY_MAX_SEC,
            )
            matches: set[str] = set()
            for candidate in await _visible_candidates(search_page, AUTHOR_PROFILE_SELECTOR):
                href = await _attribute(candidate, "href")
                name = _normalize(await _inner_text(candidate))
                if not href or not _author_name_matches(name, author):
                    continue
                candidate_id = _profile_id_from_href(href)
                if candidate_id:
                    matches.add(candidate_id)
            if len(matches) != 1:
                return _failed(
                    "FOLLOW_PROFILE_NOT_UNIQUE", "exactly one exact author profile was found"
                )
            profile_id = next(iter(matches))
        profile_url = "https://space.bilibili.com/" + profile_id
        profile_page = await self.browser.open(profile_url)
        # The profile page is a hydrated SPA.  During navigation Bilibili can
        # briefly expose zero or duplicate follow controls while the header
        # and relation state are mounting.  Wait for the same unique-visible
        # invariant used by the comment editor instead of failing immediately
        # at the first transient DOM snapshot.
        buttons = await self._wait_for_unique_candidates(profile_page, PROFILE_FOLLOW_SELECTOR)
        if len(buttons) != 1:
            return _failed(
                "FOLLOW_CONTROL_NOT_UNIQUE", "exactly one visible profile follow button is required"
            )
        button = buttons[0]
        status = _normalize(await _inner_text(button))
        if any(marker in status for marker in _FOLLOW_DONE_MARKERS):
            return _already("FOLLOW_ALREADY_DONE", "profile already shows followed")
        if _FOLLOW_READY_MARKER not in status:
            return _failed("FOLLOW_STATUS_UNRECOGNIZED", "profile follow status was not recognized")
        try:
            await _click(button)
        except Exception as exc:
            return _unknown(
                "FOLLOW_CLICK_UNKNOWN", f"follow click result is unknown ({type(exc).__name__})"
            )
        if await self._wait_for(
            profile_page,
            lambda: _follow_done(profile_page, button),
        ):
            return _success("FOLLOW_CONFIRMED", "profile follow button now shows followed")
        return _unknown(
            "FOLLOW_TERMINAL_UNKNOWN", "follow marker did not become active after one click"
        )

    async def _wait_for_author_name(self, page: Any) -> str:
        """Read the current dynamic publisher after its header has hydrated."""

        latest = ""
        attempts = min(self.poll_attempts, 6)
        for attempt in range(attempts):
            latest = await _first_text(page, AUTHOR_NAME_SELECTORS)
            if latest:
                return latest
            if attempt + 1 < attempts:
                wait = getattr(page, "wait_for_timeout", None)
                if callable(wait):
                    try:
                        await wait(self.poll_interval_ms)
                    except Exception:
                        pass
        return latest

    async def _wait_for_author_profile_ids(self, page: Any, author: str) -> set[str]:
        """Wait briefly for the dynamic's direct author @link to hydrate."""

        latest: set[str] = set()
        attempts = min(self.poll_attempts, 6)
        for attempt in range(attempts):
            latest = await _author_profile_ids(page, author)
            if latest:
                return latest
            if attempt + 1 < attempts:
                wait = getattr(page, "wait_for_timeout", None)
                if callable(wait):
                    try:
                        await wait(self.poll_interval_ms)
                    except Exception:
                        pass
        return latest

    async def _wait_for(self, page: Any, predicate: Any) -> bool:
        for attempt in range(self.poll_attempts):
            try:
                value = predicate()
                if inspect.isawaitable(value):
                    value = await value
                if value:
                    return True
            except Exception:
                pass
            if attempt + 1 < self.poll_attempts:
                wait = getattr(page, "wait_for_timeout", None)
                if callable(wait):
                    try:
                        await wait(self.poll_interval_ms)
                    except Exception:
                        pass
        return False

    async def _wait_for_unique_candidates(
        self, page: Any, selector: str, *, text: str | None = None
    ) -> list[Any]:
        """Allow asynchronously rendered duplicate controls to settle safely.

        Bilibili can briefly keep both the normal and placeholder comment
        editor in the DOM while the comment component hydrates.  We never
        guess between two controls: we only continue once exactly one visible
        candidate remains, otherwise the caller receives the original
        non-unique terminal result.
        """

        latest: list[Any] = []
        attempts = min(self.poll_attempts, 6)
        for attempt in range(attempts):
            latest = await _visible_candidates(page, selector, text=text)
            if len(latest) == 1:
                return latest
            if attempt + 1 < attempts:
                wait = getattr(page, "wait_for_timeout", None)
                if callable(wait):
                    try:
                        await wait(self.poll_interval_ms)
                    except Exception:
                        pass
        return latest

    async def _wait_for_unique_like_candidates(self, page: Any) -> list[Any]:
        """Resolve the outer dynamic like control without guessing a duplicate.

        Forwarded dynamics can expose duplicate generic like controls while
        the outer toolbar hydrates.  We first try the structural outer-toolbar
        selectors, then the historical generic selector, and only accept a
        candidate when one visible control is proven.  A short polling window
        handles transient hydration without weakening the ambiguity guard.
        """

        latest: list[Any] = []
        attempts = min(self.poll_attempts, 6)
        selectors = (
            LIKE_SCOPED_SELECTOR,
            LIKE_CONTENT_SCOPED_SELECTOR,
            LIKE_SELECTOR,
        )
        for attempt in range(attempts):
            latest = []
            for selector in selectors:
                candidates = await _visible_candidates(page, selector)
                if len(candidates) == 1:
                    return candidates
                if candidates and not latest:
                    latest = candidates
            if attempt + 1 < attempts:
                wait = getattr(page, "wait_for_timeout", None)
                if callable(wait):
                    try:
                        await wait(self.poll_interval_ms)
                    except Exception:
                        pass
        return latest


async def _visible_candidates(page: Any, selector: str, *, text: str | None = None) -> list[Any]:
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
        if text is not None and _normalize(await _inner_text(candidate)) != text:
            continue
        result.append(candidate)
    return result


async def _wait_random_delay(page: Any, minimum_sec: float, maximum_sec: float) -> None:
    """Wait a random interval using the browser page when available.

    Playwright's ``wait_for_timeout`` keeps the delay in the browser task and
    is a no-op in the lightweight test pages. The asyncio fallback preserves
    the same behavior for alternate browser adapters that do not expose that
    method.
    """

    minimum = max(0.0, minimum_sec)
    maximum = max(minimum, maximum_sec)
    delay_sec = random.uniform(minimum, maximum)
    delay_ms = int(round(delay_sec * 1000))
    wait_for_timeout = getattr(page, "wait_for_timeout", None)
    if callable(wait_for_timeout):
        try:
            await wait_for_timeout(delay_ms)
            return
        except Exception:
            pass
    await asyncio.sleep(delay_sec)


async def _visible_count(page: Any, selector: str) -> int:
    return len(await _visible_candidates(page, selector))


async def _visible_count_any(page: Any, selectors: tuple[str, ...]) -> bool:
    for selector in selectors:
        if await _visible_count(page, selector) > 0:
            return True
    return False


async def _inner_text(locator: Any) -> str:
    method = getattr(locator, "inner_text", None)
    if not callable(method):
        return ""
    try:
        return str(await method(timeout=2_000))
    except TypeError:
        return str(await method())
    except Exception:
        return ""


async def _first_text(page: Any, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        values = await _visible_candidates(page, selector)
        if values:
            value = _normalize(await _inner_text(values[0]))
            if value:
                return value
    return ""


async def _author_profile_ids(page: Any, author: str) -> set[str]:
    """Return numeric profile ids from visible links naming the dynamic author."""

    result: set[str] = set()
    for candidate in await _visible_candidates(page, AUTHOR_PROFILE_SELECTOR):
        href = await _attribute(candidate, "href")
        if not href or not _author_name_matches(_normalize(await _inner_text(candidate)), author):
            continue
        profile_id = _profile_id_from_href(href)
        if profile_id:
            result.add(profile_id)
    return result


def _author_name_matches(display_name: str, author: str) -> bool:
    """Match both the header name and the @mention form used by opus pages."""

    normalized_display = _normalize(display_name).lstrip("@").strip()
    normalized_author = _normalize(author).lstrip("@").strip()
    return bool(normalized_display and normalized_display == normalized_author)


def _profile_id_from_href(href: str) -> str:
    profile_parts = urlsplit("https:" + href if href.startswith("//") else href)
    path_parts = profile_parts.path.strip("/").split("/")
    profile_id = path_parts[-1] if path_parts else ""
    return profile_id if profile_id.isdigit() else ""


async def _attribute(locator: Any, name: str) -> str:
    method = getattr(locator, "get_attribute", None)
    if not callable(method):
        return ""
    try:
        return str(await method(name) or "")
    except Exception:
        return ""


async def _fill(locator: Any, value: str) -> None:
    method = getattr(locator, "fill", None)
    if not callable(method):
        raise RuntimeError("LOCATOR_FILL_UNAVAILABLE")
    await method(value)


async def _click(locator: Any) -> None:
    method = getattr(locator, "click", None)
    if not callable(method):
        raise RuntimeError("LOCATOR_CLICK_UNAVAILABLE")
    await method(timeout=15_000)


async def _checked(locator: Any) -> bool:
    attr = _normalize(await _attribute(locator, "checked")).lower()
    if attr in {"true", "checked", "1"}:
        return True
    method = getattr(locator, "is_checked", None)
    if callable(method):
        try:
            return bool(await method())
        except Exception:
            return False
    return False


async def _is_checked(locator: Any) -> bool:
    return await _checked(locator)


async def _page_text(page: Any) -> str:
    locator_factory = getattr(page, "locator", None)
    if not callable(locator_factory):
        return ""
    try:
        return _normalize(await _inner_text(locator_factory("body")))
    except Exception:
        return ""


async def _security_page(page: Any) -> bool:
    text = await _page_text(page)
    return any(marker in text for marker in _SECURITY_MARKERS)


async def _has_any_success_marker(page: Any) -> bool:
    text = await _page_text(page)
    return any(marker in text for marker in _SUCCESS_MARKERS)


async def _share_terminal(page: Any) -> bool:
    return await _visible_count(page, SHARE_SELECTOR) == 0 and await _has_any_success_marker(page)


async def _follow_done(page: Any, button: Any) -> bool:
    status = _normalize(await _inner_text(button))
    if any(marker in status for marker in _FOLLOW_DONE_MARKERS):
        return True
    page_text = await _page_text(page)
    return any(marker in page_text for marker in _FOLLOW_DONE_MARKERS)


def _normalize(value: str) -> str:
    return " ".join(value.replace("\u200b", "").replace("\ufeff", "").split())


def _success(
    code: str, message: str, *, confirmed_actions: tuple[str, ...] = ()
) -> WriteOperationResult:
    return WriteOperationResult(WriteOutcomeState.SUCCESS, code, message, confirmed_actions)


def _already(code: str, message: str) -> WriteOperationResult:
    return WriteOperationResult(WriteOutcomeState.ALREADY_DONE, code, message)


def _unknown(code: str, message: str) -> WriteOperationResult:
    return WriteOperationResult(WriteOutcomeState.UNKNOWN, code, message)


def _failed(code: str, message: str) -> WriteOperationResult:
    return WriteOperationResult(WriteOutcomeState.FAILED, code, message)


__all__ = [
    "DomUnofficialTransport",
    "LIKE_ACTIVE_SELECTORS",
    "LIKE_SCOPED_SELECTOR",
    "UNOFFICIAL_WRITE_SELECTOR_VERSION",
]
