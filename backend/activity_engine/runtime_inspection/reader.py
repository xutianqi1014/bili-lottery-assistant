"""Read one currently executing activity page.

This module is intentionally single-item only.  It must never enumerate a
discovery or open future run items as a batch.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from backend.activity_engine.models import ActivitySnapshot
from backend.activity_engine.unofficial.page_evidence import (
    UNOFFICIAL_SELECTOR_VERSION,
    read_unofficial_page_evidence,
)
from backend.browser.manager import BrowserManager

_TAG_RE = re.compile(r"<[^>]+>")
_ID_RE = re.compile(r"/(?:opus|dynamic)/([0-9]+)/?$", re.IGNORECASE)
_T_ID_RE = re.compile(r"/([0-9]+)/?$")
_EXPIRED_RE = re.compile(r"抽奖已失效|抽奖已结束|活动已结束|抽奖不存在")
_COUNTDOWN_RE = re.compile(r"开奖倒计时|距离开奖|倒计时")
_DRAW_TIME_RE = re.compile(r"开奖时间\s*[:：]?")
_PARTICIPATED_RE = re.compile(r"已成功参与|成功参与|已转发|转发成功|已参与|参与成功|您已参加")
_LOTTERY_ENTRY_SELECTOR = 'a[data-type="lottery"]'
_LOTTERY_IFRAME_SELECTOR = 'iframe[src*="/h5/lottery/result"]'
_LOTTERY_DIALOG_SELECTORS = (
    'div[role="dialog"]',
    'div.bili-dialog',
    '[class*="lottery-dialog"]',
)
_LOTTERY_FRAME_HINT = "/h5/lottery/result"
_LIKE_ACTIVE_SELECTORS = (
    ".side-toolbar__action.like.is-active",
    '.side-toolbar__action.like[aria-pressed="true"]',
    '.side-toolbar__action.like[data-state="active"]',
    '.side-toolbar__action.like[data-liked="true"]',
    '.side-toolbar__action.like[class*="liked"]',
)
_PANEL_WAIT_ATTEMPTS = 10
_PANEL_WAIT_INTERVAL_MS = 500
_PANEL_TEXT_WAIT_ATTEMPTS = 10
_PANEL_TEXT_WAIT_INTERVAL_MS = 500
_PANEL_TEXT_READ_TIMEOUT_MS = 1_000


@dataclass(frozen=True)
class RuntimeActivityRead:
    snapshot: ActivitySnapshot
    body_excerpt: str
    page_title: str
    lottery_entry_opened: bool = False
    lottery_panel_selector: str | None = None
    lottery_panel_text: str = ""
    lottery_panel_error: str | None = None
    selector_version: str = "activity-page-v3-like-state"
    nonofficial_outer_text: str = ""
    nonofficial_forwarded_original_text: str = ""
    nonofficial_has_forwarded_original: bool = False
    nonofficial_comment_editor_present: bool = False
    nonofficial_comment_publish_present: bool = False
    nonofficial_comment_repost_control_present: bool = False
    nonofficial_author_name: str = ""
    nonofficial_evidence_codes: tuple[str, ...] = ()
    nonofficial_selector_version: str = UNOFFICIAL_SELECTOR_VERSION


class RuntimeActivityReader:
    async def read(
        self,
        browser: BrowserManager,
        dynamic_id: str,
        canonical_url: str,
        *,
        post_open_delay_sec: float = 0.0,
    ) -> RuntimeActivityRead:
        page = await browser.open(canonical_url)
        final_url = str(getattr(page, "url", "") or "")
        self._assert_identity(final_url, dynamic_id)
        # A non-official dynamic is opened in the visible browser before its
        # scoped body and controls are inspected.  The caller supplies the
        # configured random delay so the first read is not issued immediately
        # after navigation.  Keep the default at zero for direct readers and
        # tests; official pages must not inherit this non-official throttle.
        delay = max(0.0, float(post_open_delay_sec))
        if delay > 0:
            await asyncio.sleep(delay)
        body_text, html = await self._read_body(page)
        title = await self._read_title(page)
        unofficial_evidence = await read_unofficial_page_evidence(page)
        has_official_entry = await self._has_locator(page, _LOTTERY_ENTRY_SELECTOR)
        if not has_official_entry:
            has_official_entry = bool(re.search(r'data-type=["\']lottery["\']', html))

        activity_like_active = False
        for selector in _LIKE_ACTIVE_SELECTORS:
            if await self._has_visible_locator(page, selector):
                activity_like_active = True
                break
        lottery_panel = _LotteryPanelRead()
        if has_official_entry and not activity_like_active:
            lottery_panel = await self._open_lottery_panel(page)
            if lottery_panel.text:
                body_text = f"{body_text}\n{lottery_panel.text}"

        visible_text = _clean_text(body_text)
        panel_text = _clean_text(lottery_panel.text)
        actionable_text = unofficial_evidence.outer_text or visible_text
        expired_text = (
            not bool(_DRAW_TIME_RE.search(panel_text))
            if has_official_entry and lottery_panel.opened and panel_text
            else (_is_expired_text(visible_text) if not has_official_entry else False)
        )
        return RuntimeActivityRead(
            snapshot=ActivitySnapshot(
                dynamic_id=dynamic_id,
                canonical_url=canonical_url,
                body_text=visible_text,
                has_official_lottery_entry=has_official_entry,
                official_lottery_panel_opened=lottery_panel.opened,
                official_lottery_panel_error=lottery_panel.error_code,
                activity_like_active=activity_like_active,
                already_participated_text=bool(_PARTICIPATED_RE.search(visible_text)),
                expired_text=expired_text,
                actionable_text=actionable_text,
                forwarded_original_text=unofficial_evidence.forwarded_original_text,
                has_forwarded_original=unofficial_evidence.has_forwarded_original,
                nonofficial_dom_evidence=unofficial_evidence.evidence_codes,
            ),
            body_excerpt=visible_text[:2000],
            page_title=_clean_text(title),
            lottery_entry_opened=lottery_panel.opened,
            lottery_panel_selector=lottery_panel.selector,
            lottery_panel_text=lottery_panel.text[:4000],
            lottery_panel_error=lottery_panel.error_code,
            nonofficial_outer_text=unofficial_evidence.outer_text[:4000],
            nonofficial_forwarded_original_text=(
                unofficial_evidence.forwarded_original_text[:4000]
            ),
            nonofficial_has_forwarded_original=(
                unofficial_evidence.has_forwarded_original
            ),
            nonofficial_comment_editor_present=(
                unofficial_evidence.comment_editor_present
            ),
            nonofficial_comment_publish_present=(
                unofficial_evidence.comment_publish_present
            ),
            nonofficial_comment_repost_control_present=(
                unofficial_evidence.comment_repost_control_present
            ),
            nonofficial_author_name=unofficial_evidence.author_name,
            nonofficial_evidence_codes=unofficial_evidence.evidence_codes,
        )

    @classmethod
    async def _open_lottery_panel(cls, page: object) -> _LotteryPanelRead:
        locator_factory = getattr(page, "locator", None)
        if not callable(locator_factory):
            return _LotteryPanelRead(error_code="OFFICIAL_LOTTERY_ENTRY_CLICK_FAILED")

        try:
            entry = locator_factory(_LOTTERY_ENTRY_SELECTOR)
            entry = getattr(entry, "first", entry)
            scroll_into_view = getattr(entry, "scroll_into_view_if_needed", None)
            if callable(scroll_into_view):
                await scroll_into_view(timeout=15_000)
            click = getattr(entry, "click", None)
            if not callable(click):
                return _LotteryPanelRead(error_code="OFFICIAL_LOTTERY_ENTRY_CLICK_FAILED")
            await click(timeout=15_000)
        except Exception:
            return _LotteryPanelRead(error_code="OFFICIAL_LOTTERY_ENTRY_CLICK_FAILED")

        selector = await cls._wait_for_lottery_surface(page)
        if selector is None:
            return _LotteryPanelRead(error_code="OFFICIAL_LOTTERY_PANEL_NOT_FOUND")

        text = await cls._read_lottery_surface_text(page, selector)
        if not text:
            return _LotteryPanelRead(
                opened=True,
                selector=selector,
                error_code="OFFICIAL_LOTTERY_PANEL_TEXT_EMPTY",
            )
        return _LotteryPanelRead(opened=True, selector=selector, text=text)

    @classmethod
    async def _wait_for_lottery_surface(cls, page: object) -> str | None:
        for attempt in range(_PANEL_WAIT_ATTEMPTS):
            if await cls._has_visible_locator(page, _LOTTERY_IFRAME_SELECTOR):
                return _LOTTERY_IFRAME_SELECTOR
            for selector in _LOTTERY_DIALOG_SELECTORS:
                if await cls._has_visible_locator(page, selector):
                    return selector
            if attempt + 1 < _PANEL_WAIT_ATTEMPTS:
                wait_for_timeout = getattr(page, "wait_for_timeout", None)
                if callable(wait_for_timeout):
                    try:
                        await wait_for_timeout(_PANEL_WAIT_INTERVAL_MS)
                    except Exception:
                        pass
        return None

    @classmethod
    async def _read_lottery_surface_text(cls, page: object, selector: str) -> str:
        # B站先创建 iframe，再异步填充正文。只检查一次会在 iframe 已可见、
        # 但正文尚未 hydrate 时得到空字符串，正是“面板打开但没有判断”的场景。
        for attempt in range(_PANEL_TEXT_WAIT_ATTEMPTS):
            text = ""
            if selector == _LOTTERY_IFRAME_SELECTOR:
                text = await cls._read_lottery_frame_text(
                    page, timeout_ms=_PANEL_TEXT_READ_TIMEOUT_MS
                )
            if not text:
                text = await cls._read_locator_text(
                    page, selector, timeout_ms=_PANEL_TEXT_READ_TIMEOUT_MS
                )
            if text:
                return text
            if attempt + 1 < _PANEL_TEXT_WAIT_ATTEMPTS:
                await cls._wait_for_timeout(page, _PANEL_TEXT_WAIT_INTERVAL_MS)
        return ""

    @staticmethod
    async def _read_locator_text(page: object, selector: str, *, timeout_ms: int) -> str:
        locator_factory = getattr(page, "locator", None)
        if not callable(locator_factory):
            return ""
        try:
            locator = locator_factory(selector)
            inner_text = getattr(locator, "inner_text", None)
            if callable(inner_text):
                return _clean_text(str(await inner_text(timeout=timeout_ms)))
        except Exception:
            pass
        return ""

    @staticmethod
    async def _read_lottery_frame_text(page: object, *, timeout_ms: int) -> str:
        frames = getattr(page, "frames", ())
        if callable(frames):
            try:
                frames = frames()
            except Exception:
                frames = ()
        for frame in frames or ():
            frame_url = str(getattr(frame, "url", "") or "")
            if _LOTTERY_FRAME_HINT not in frame_url:
                continue
            locator_factory = getattr(frame, "locator", None)
            if not callable(locator_factory):
                continue
            try:
                body = locator_factory("body")
                inner_text = getattr(body, "inner_text", None)
                if callable(inner_text):
                    text = _clean_text(str(await inner_text(timeout=timeout_ms)))
                    if text:
                        return text
            except Exception:
                continue

        frame_locator_factory = getattr(page, "frame_locator", None)
        if callable(frame_locator_factory):
            try:
                body = frame_locator_factory(_LOTTERY_IFRAME_SELECTOR).locator("body")
                inner_text = getattr(body, "inner_text", None)
                if callable(inner_text):
                    return _clean_text(str(await inner_text(timeout=timeout_ms)))
            except Exception:
                pass
        return ""

    @staticmethod
    async def _wait_for_timeout(page: object, timeout_ms: int) -> None:
        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if callable(wait_for_timeout):
            try:
                await wait_for_timeout(timeout_ms)
            except Exception:
                pass

    @staticmethod
    def _assert_identity(final_url: str, dynamic_id: str) -> None:
        if not final_url:
            return
        parsed = urlsplit(final_url)
        match = _ID_RE.search(parsed.path)
        # B站 may canonicalize an opus URL to the legacy short host form
        # ``https://t.bilibili.com/{dynamic_id}``.  It is the same dynamic,
        # but the host must be checked explicitly so an arbitrary external
        # numeric path can never satisfy the fallback.
        if match is None and (parsed.hostname or "").casefold() == "t.bilibili.com":
            match = _T_ID_RE.fullmatch(parsed.path)
        if match is None or match.group(1) != dynamic_id:
            raise ValueError("ACTIVITY_ID_MISMATCH")

    @staticmethod
    async def _read_body(page: object) -> tuple[str, str]:
        html = ""
        content = getattr(page, "content", None)
        if callable(content):
            html = str(await content())
        locator = getattr(page, "locator", None)
        if callable(locator):
            try:
                body = locator("body")
                body_text = str(await body.inner_text(timeout=30_000))
            except Exception:
                body_text = _strip_html(html)
        else:
            body_text = _strip_html(html)
        return body_text, html

    @staticmethod
    async def _read_title(page: object) -> str:
        title = getattr(page, "title", None)
        if callable(title):
            try:
                return str(await title())
            except Exception:
                return ""
        return ""

    @staticmethod
    async def _has_locator(page: object, selector: str) -> bool:
        locator_factory = getattr(page, "locator", None)
        if not callable(locator_factory):
            return False
        try:
            locator = locator_factory(selector)
            count = getattr(locator, "count", None)
            return bool(await count()) if callable(count) else False
        except Exception:
            return False

    @staticmethod
    async def _has_visible_locator(page: object, selector: str) -> bool:
        locator_factory = getattr(page, "locator", None)
        if not callable(locator_factory):
            return False
        try:
            locator = locator_factory(selector)
            count = getattr(locator, "count", None)
            if callable(count):
                total = int(await count())
                if total <= 0:
                    return False
                nth = getattr(locator, "nth", None)
                if callable(nth):
                    for index in range(total):
                        candidate = nth(index)
                        is_visible = getattr(candidate, "is_visible", None)
                        if callable(is_visible) and await is_visible():
                            return True
                    return False
            is_visible = getattr(locator, "is_visible", None)
            if callable(is_visible):
                return bool(await is_visible())
            return bool(await count()) if callable(count) else False
        except Exception:
            return False


def _strip_html(value: str) -> str:
    return _TAG_RE.sub(" ", html_lib.unescape(value))


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\u200b", "").replace("\ufeff", "").split())


def _is_expired_text(value: str) -> bool:
    """判定明确终态，避免用隐藏/残留文案覆盖活跃倒计时。

    官方抽奖面板中的“开奖倒计时”是比整页历史文案更强的活跃信号；
    只要仍有倒计时，就不能把动态标记为已结束。面板未打开时才使用
    动态正文中的明确终态词。"""

    if _COUNTDOWN_RE.search(value):
        return False
    return bool(_EXPIRED_RE.search(value))


@dataclass(frozen=True)
class _LotteryPanelRead:
    opened: bool = False
    selector: str | None = None
    text: str = ""
    error_code: str | None = None
