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
# B站会把已删除、已下架或已经不可见的动态渲染成一个错误页。部分
# 账号只能看到标题“出错啦! - bilibili.com”和“返回上一页/换一张”，
# 正文不会包含更明确的“动态已删除”文案，因此两类信号都要支持。
_UNAVAILABLE_TITLE_RE = re.compile(r"(?:出错啦|页面不存在|找不到页面|404)", re.IGNORECASE)
_UNAVAILABLE_EXPLICIT_BODY_RE = re.compile(
    r"动态不存在|动态已被删除|内容不存在|内容已被删除|内容已不可见|"
    r"动态已失效|该内容已被删除|暂时无法查看|页面不存在|找不到页面",
    re.IGNORECASE,
)
_UNAVAILABLE_ERROR_SHELL_RE = re.compile(r"返回上一页\s*换一张", re.IGNORECASE)
_COUNTDOWN_RE = re.compile(r"开奖倒计时|距离开奖|倒计时")
_DRAW_TIME_RE = re.compile(r"开奖时间\s*[:：]?")
_RESERVATION_CONTROL_RE = re.compile(r"^(?:预约|已预约)$")
# 预约抽奖的唯一分类信号是预约卡片中的“预约有奖”文案。按钮变成
# “已结束”或“去观看”只表示该卡片不可执行，不单独把普通动态分类成预约。
_RESERVATION_CARD_RE = re.compile(r"预约\s*有奖")
_RESERVATION_TERMINAL_RE = re.compile(r"^(?:已结束|预约已结束|预约已过期|已取消)$")
_RESERVATION_WATCH_ONLY_RE = re.compile(r"^去观看$")
_RESERVATION_BUTTON_SELECTOR = ".bili-dyn-card-reserve__card button"
_RESERVATION_MARKER_SELECTOR = ".bili-dyn-card-reserve__lottery__text"
_PARTICIPATED_RE = re.compile(r"已成功参与|成功参与|已转发|转发成功|已参与|参与成功|您已参加")
_LOTTERY_ENTRY_SELECTOR = 'a[data-type="lottery"]'
_FORWARDED_ORIGINAL_SELECTOR = ".bili-dyn-content__orig.reference"
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
_RESERVATION_WAIT_ATTEMPTS = 8
_RESERVATION_WAIT_INTERVAL_MS = 300


@dataclass(frozen=True)
class RuntimeActivityRead:
    snapshot: ActivitySnapshot
    body_excerpt: str
    page_title: str
    dynamic_unavailable: bool = False
    lottery_entry_opened: bool = False
    lottery_panel_selector: str | None = None
    lottery_panel_text: str = ""
    lottery_panel_error: str | None = None
    reservation_entry_present: bool = False
    reservation_active: bool = False
    reservation_control_text: str = ""
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
        clean_body = _clean_text(body_text)
        clean_title = _clean_text(title)
        if _is_unavailable_dynamic_page(clean_title, clean_body):
            # Do not continue into lottery/reservation/non-official DOM
            # inspection.  The error page has no participation surface and
            # must be represented as a safe, terminal skip by the run layer.
            return RuntimeActivityRead(
                snapshot=ActivitySnapshot(
                    dynamic_id=dynamic_id,
                    canonical_url=canonical_url,
                    body_text=clean_body,
                    expired_text=True,
                    actionable_text=clean_body,
                ),
                body_excerpt=clean_body[:2000],
                page_title=clean_title,
                dynamic_unavailable=True,
            )

        # The dynamic like marker is the cross-run participation marker for
        # every supported activity type. Read it before collecting any
        # type-specific evidence. Once it is active, the caller can safely
        # skip the item without opening a lottery panel, reading a reservation
        # card, parsing non-official requirements, or applying a source type
        # allow-list. This also avoids needless DOM reads on handled dynamics.
        activity_like_active = False
        for selector in _LIKE_ACTIVE_SELECTORS:
            if await self._has_visible_locator(page, selector):
                activity_like_active = True
                break
        if activity_like_active:
            return RuntimeActivityRead(
                snapshot=ActivitySnapshot(
                    dynamic_id=dynamic_id,
                    canonical_url=canonical_url,
                    body_text=clean_body,
                    activity_like_active=True,
                    already_participated_text=True,
                    actionable_text=clean_body,
                ),
                body_excerpt=clean_body[:2000],
                page_title=clean_title,
            )

        unofficial_evidence = await read_unofficial_page_evidence(page)
        reservation = await self._read_reservation_control(page, body_text)
        # A boosted dynamic can contain the original dynamic's official
        # lottery link inside `.bili-dyn-content__orig.reference`.  That
        # nested link belongs to the quoted original, not to the current
        # outer dynamic.  Counting entries outside that forwarded-original
        # subtree prevents the outer item from being reclassified as an
        # official target (which would later fail the confirmed-run scope
        # check and could select the wrong writer).
        total_lottery_entries = await self._locator_count(page, _LOTTERY_ENTRY_SELECTOR)
        nested_lottery_entries = (
            await self._locator_count(
                page,
                f"{_FORWARDED_ORIGINAL_SELECTOR} {_LOTTERY_ENTRY_SELECTOR}",
            )
            if unofficial_evidence.has_forwarded_original
            else 0
        )
        has_official_entry = total_lottery_entries > (
            nested_lottery_entries if unofficial_evidence.has_forwarded_original else 0
        )
        nested_official_entry_ignored = bool(
            unofficial_evidence.has_forwarded_original
            and nested_lottery_entries > 0
            and nested_lottery_entries >= total_lottery_entries
        )
        if not has_official_entry and not unofficial_evidence.has_forwarded_original:
            has_official_entry = bool(re.search(r'data-type=["\']lottery["\']', html))

        nonofficial_evidence_codes = list(unofficial_evidence.evidence_codes)
        if nested_official_entry_ignored:
            nonofficial_evidence_codes.append("BOOSTED_NESTED_OFFICIAL_ENTRY_IGNORED")

        lottery_panel = _LotteryPanelRead()
        if has_official_entry and not activity_like_active:
            lottery_panel = await self._open_lottery_panel(page)
            if lottery_panel.text:
                body_text = f"{body_text}\n{lottery_panel.text}"

        # The official panel text is appended to ``body_text`` above; use the
        # final value here so pre-click participation and expiry markers remain
        # visible to the shared classifier.
        visible_text = _clean_text(body_text)
        panel_text = _clean_text(lottery_panel.text)
        actionable_text = unofficial_evidence.outer_text or visible_text
        reservation_terminal = bool(
            reservation.present
            and (
                _RESERVATION_TERMINAL_RE.fullmatch(reservation.text)
                or _RESERVATION_WATCH_ONLY_RE.fullmatch(reservation.text)
            )
        )
        expired_text = (
            not bool(_DRAW_TIME_RE.search(panel_text))
            if has_official_entry and lottery_panel.opened and panel_text
            else (
                (_is_expired_text(visible_text) or reservation_terminal)
                if not has_official_entry
                else False
            )
        )
        return RuntimeActivityRead(
            snapshot=ActivitySnapshot(
                dynamic_id=dynamic_id,
                canonical_url=canonical_url,
                body_text=visible_text,
                has_official_lottery_entry=has_official_entry,
                has_reservation_entry=reservation.present,
                reservation_active=reservation.active,
                reservation_control_text=reservation.text,
                official_lottery_panel_opened=lottery_panel.opened,
                official_lottery_panel_error=lottery_panel.error_code,
                activity_like_active=activity_like_active,
                already_participated_text=bool(_PARTICIPATED_RE.search(visible_text)),
                expired_text=expired_text,
                actionable_text=actionable_text,
                forwarded_original_text=unofficial_evidence.forwarded_original_text,
                has_forwarded_original=unofficial_evidence.has_forwarded_original,
                nonofficial_dom_evidence=tuple(dict.fromkeys(nonofficial_evidence_codes)),
            ),
            body_excerpt=visible_text[:2000],
            page_title=_clean_text(title),
            lottery_entry_opened=lottery_panel.opened,
            lottery_panel_selector=lottery_panel.selector,
            lottery_panel_text=lottery_panel.text[:4000],
            lottery_panel_error=lottery_panel.error_code,
            reservation_entry_present=reservation.present,
            reservation_active=reservation.active,
            reservation_control_text=reservation.text,
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
            nonofficial_evidence_codes=tuple(dict.fromkeys(nonofficial_evidence_codes)),
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
    async def _locator_count(page: object, selector: str) -> int:
        locator_factory = getattr(page, "locator", None)
        if not callable(locator_factory):
            return 0
        try:
            locator = locator_factory(selector)
            count = getattr(locator, "count", None)
            return int(await count()) if callable(count) else 0
        except Exception:
            return 0

    @classmethod
    async def _read_reservation_control(
        cls, page: object, body_text: str = ""
    ) -> _ReservationControlRead:
        """Read reservation-card state without opening or clicking it.

        The button labels ``已结束`` and ``去观看`` are only terminal states.
        They are accepted here only after the page has independently exposed
        the exact ``预约有奖`` card marker; neither is a reservation
        classifier signal on its own.
        """

        locator_factory = getattr(page, "locator", None)
        if not callable(locator_factory):
            return _ReservationControlRead()
        has_card_marker = await cls._has_reservation_card_marker(page, body_text)
        # A button label alone is never enough.  Only the reserve card that
        # carries the exact “预约有奖” marker may expose reservation controls.
        if not has_card_marker:
            return _ReservationControlRead()
        for attempt in range(_RESERVATION_WAIT_ATTEMPTS):
            try:
                controls = locator_factory(_RESERVATION_BUTTON_SELECTOR)
                total = int(await controls.count())
                labels: list[str] = []
                terminal_labels: list[str] = []
                nth = getattr(controls, "nth", None)
                for index in range(total):
                    if callable(nth):
                        control = nth(index)
                    elif total == 1 and index == 0:
                        control = controls
                    else:
                        continue
                    is_visible = getattr(control, "is_visible", None)
                    if callable(is_visible) and not await is_visible():
                        continue
                    inner_text = getattr(control, "inner_text", None)
                    if not callable(inner_text):
                        continue
                    label = _clean_text(str(await inner_text(timeout=1_000)))
                    if _RESERVATION_CONTROL_RE.fullmatch(label):
                        labels.append(label)
                    elif has_card_marker and (
                        _RESERVATION_TERMINAL_RE.fullmatch(label)
                        or _RESERVATION_WATCH_ONLY_RE.fullmatch(label)
                    ):
                        terminal_labels.append(label)
                if labels:
                    unbooked = sum(label == "预约" for label in labels)
                    active = sum(label == "已预约" for label in labels)
                    # A simultaneous duplicate active/unbooked snapshot is not
                    # treated as participated; the writer will fail closed.
                    return _ReservationControlRead(
                        present=True,
                        active=active > 0 and unbooked == 0,
                        text="、".join(dict.fromkeys(labels)),
                    )
                if has_card_marker:
                    if len(terminal_labels) == 1:
                        return _ReservationControlRead(
                            present=True,
                            active=False,
                            text=terminal_labels[0],
                        )
                    # The card itself is enough to classify the dynamic; if
                    # its action control is absent/ambiguous, the writer will
                    # stop safely instead of opening an official panel.
                    return _ReservationControlRead(
                        present=True,
                        active=False,
                        text="预约有奖",
                    )
            except Exception:
                pass
            if attempt + 1 < _RESERVATION_WAIT_ATTEMPTS:
                await cls._wait_for_timeout(page, _RESERVATION_WAIT_INTERVAL_MS)
        return _ReservationControlRead()

    @classmethod
    async def _has_reservation_card_marker(cls, page: object, body_text: str) -> bool:
        """Prefer the verified reserve-card marker, then use body text fallback."""

        locator_factory = getattr(page, "locator", None)
        if callable(locator_factory):
            try:
                marker = locator_factory(_RESERVATION_MARKER_SELECTOR)
                total = int(await marker.count())
                nth = getattr(marker, "nth", None)
                for index in range(total):
                    candidate = nth(index) if callable(nth) else marker
                    visible = getattr(candidate, "is_visible", None)
                    if callable(visible) and not await visible():
                        continue
                    inner_text = getattr(candidate, "inner_text", None)
                    if callable(inner_text) and _RESERVATION_CARD_RE.search(
                        _clean_text(str(await inner_text(timeout=1_000)))
                    ):
                        return True
                if total > 0:
                    return False
            except Exception:
                pass
        return bool(_RESERVATION_CARD_RE.search(_clean_text(body_text)))

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


def _is_unavailable_dynamic_page(title: str, body_text: str) -> bool:
    """Return whether B站 rendered the requested dynamic as an error page.

    A title marker or a deletion phrase alone is intentionally insufficient:
    normal dynamic text/comments can contain similar words.  We require two
    independent signals: an error title or the error-page action shell, plus
    either the shell or explicit deletion/unavailability copy.
    """

    title_match = bool(_UNAVAILABLE_TITLE_RE.search(_clean_text(title)))
    body_match = bool(_UNAVAILABLE_EXPLICIT_BODY_RE.search(_clean_text(body_text)))
    shell_match = bool(_UNAVAILABLE_ERROR_SHELL_RE.search(_clean_text(body_text)))
    return (title_match or shell_match) and (body_match or shell_match)


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


@dataclass(frozen=True)
class _ReservationControlRead:
    present: bool = False
    active: bool = False
    text: str = ""
