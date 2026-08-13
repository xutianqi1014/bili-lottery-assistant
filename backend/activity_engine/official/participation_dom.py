"""Visible DOM transport for one official lottery participation.

The outer lottery entry is opened first, then the embedded lottery panel is
read.  A participation control is clicked only when its text matches the
small allowlist below and exactly one candidate exists.  After a newly
confirmed participation, the lottery popup is closed before the separate
dynamic-like marker module is allowed to click the outer toolbar.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Protocol

from .activity_like_marker import (
    ActivityLikeMarkerState,
    ensure_activity_like_marker,
    inspect_activity_like_marker,
)
from .participation import (
    OfficialParticipationOutcomeState,
    OfficialParticipationWriteResult,
    validate_official_participation_target,
)

LOTTERY_ENTRY_SELECTOR = 'a[data-type="lottery"]'
LOTTERY_IFRAME_SELECTOR = 'iframe[src*="/h5/lottery/result"]'
LOTTERY_PANEL_CLOSE_SELECTOR = ".bili-popup__header__close"
LOTTERY_PARTICIPATION_CONTROLS_SELECTOR = (
    'button,[role="button"],a,div.join-button'
)
LOTTERY_SELECTOR_VERSION = "official_participation_dom_v2"
PARTICIPATION_TEXT_ALLOWLIST = (
    "关注up主并转发抽奖动态",
    "关注我并转发抽奖动态",
    "转发抽奖动态",
)
_DONE_RE = re.compile(r"已成功参与|参与成功|已参与|已转发|转发成功|您已参加")
_DRAW_TIME_RE = re.compile(r"开奖时间\s*[:：]?")
_SECURITY_RE = re.compile(r"验证码|人机验证|安全验证|风控|请先登录|登录后")
_PANEL_TEXT_ATTEMPTS = 10
_PANEL_TEXT_INTERVAL_MS = 500
_POLL_ATTEMPTS = 30
_POLL_INTERVAL_MS = 500


class OfficialParticipationPage(Protocol):
    async def wait_for_selector(self, selector: str, *, timeout: int) -> Any: ...

    def locator(self, selector: str) -> Any: ...

    def frame_locator(self, selector: str) -> Any: ...

    async def wait_for_timeout(self, timeout: int) -> None: ...


class OfficialParticipationBrowser(Protocol):
    async def open(self, url: str) -> OfficialParticipationPage: ...


class DomOfficialParticipationTransport:
    """Open one official panel, click one validated control, and verify text."""

    def __init__(self, browser: OfficialParticipationBrowser, timeout_ms: int = 15_000):
        self.browser = browser
        self.timeout_ms = timeout_ms

    async def perform(
        self,
        *,
        target_url: str,
        payload: Mapping[str, object],
    ) -> OfficialParticipationWriteResult:
        del payload
        validate_official_participation_target(target_url)
        try:
            page = await self.browser.open(target_url)
            like_marker = await inspect_activity_like_marker(
                page,
                timeout_ms=self.timeout_ms,
            )
            if like_marker.state is ActivityLikeMarkerState.LIKED:
                return OfficialParticipationWriteResult(
                    OfficialParticipationOutcomeState.ALREADY_PARTICIPATED,
                    "ALREADY_PARTICIPATED_LIKED",
                    "official activity is already liked and is treated as participated",
                )
            if like_marker.state is ActivityLikeMarkerState.UNKNOWN:
                return OfficialParticipationWriteResult(
                    OfficialParticipationOutcomeState.UNKNOWN,
                    like_marker.code,
                    like_marker.message,
                )
            entry = page.locator(LOTTERY_ENTRY_SELECTOR)
            count = await entry.count()
        except Exception as exc:  # noqa: BLE001 - page state is not reliable
            return _unknown("OFFICIAL_LOTTERY_PAGE_READ_UNKNOWN", exc)
        if count == 0:
            return _failed(
                "OFFICIAL_LOTTERY_ENTRY_NOT_FOUND",
                "official lottery entry was not found",
            )
        if count != 1:
            return _failed(
                "OFFICIAL_LOTTERY_ENTRY_AMBIGUOUS",
                "official lottery entry count is ambiguous",
            )

        try:
            scroll = getattr(entry, "scroll_into_view_if_needed", None)
            if callable(scroll):
                await scroll(timeout=self.timeout_ms)
            await entry.click(timeout=self.timeout_ms)
            await page.wait_for_selector(LOTTERY_IFRAME_SELECTOR, timeout=self.timeout_ms)
            panel = page.frame_locator(LOTTERY_IFRAME_SELECTOR)
            text = await _read_panel_text(panel, page, self.timeout_ms)
        except Exception as exc:  # noqa: BLE001 - panel state is uncertain
            return _unknown("OFFICIAL_LOTTERY_PANEL_OPEN_UNKNOWN", exc)
        if not text:
            return _failed(
                "OFFICIAL_LOTTERY_PANEL_TEXT_EMPTY",
                "official lottery panel opened but its text stayed empty",
            )

        already_participated = _classify_preclick_already_participated(text)
        if already_participated is not None:
            return already_participated

        terminal = classify_official_panel_text(text)
        if terminal is not None:
            return terminal

        try:
            candidates = await _read_participation_candidates(
                panel,
                page,
                self.timeout_ms,
            )
        except Exception as exc:  # noqa: BLE001 - structure cannot be trusted
            return _unknown("OFFICIAL_PARTICIPATION_CONTROL_READ_UNKNOWN", exc)

        # The panel hydrates asynchronously.  Re-read its terminal text after
        # locating controls and immediately before any possible click.  This
        # preserves the legacy already-participated state even when the success
        # label appeared while the control lookup was running.
        try:
            latest_text = await _read_text(panel.locator("body"), self.timeout_ms)
        except Exception as exc:  # noqa: BLE001 - a click is unsafe without readback
            return _unknown("OFFICIAL_PARTICIPATION_PRECLICK_READ_UNKNOWN", exc)
        already_participated = _classify_preclick_already_participated(latest_text)
        if already_participated is not None:
            return already_participated

        if not candidates:
            return _failed(
                "OFFICIAL_PARTICIPATION_BUTTON_NOT_FOUND",
                "no uniquely validated official participation control was found",
            )
        if len(candidates) != 1:
            return _failed(
                "OFFICIAL_PARTICIPATION_BUTTON_AMBIGUOUS",
                "more than one official participation control matched the allowlist",
            )

        button = candidates[0]
        try:
            enabled = getattr(button, "is_enabled", None)
            if callable(enabled) and not await enabled():
                return _failed(
                    "OFFICIAL_PARTICIPATION_BUTTON_DISABLED",
                    "official participation control is disabled",
                )
            scroll = getattr(button, "scroll_into_view_if_needed", None)
            if callable(scroll):
                await scroll(timeout=self.timeout_ms)
            await button.click(timeout=self.timeout_ms)
        except Exception as exc:  # noqa: BLE001 - click may have reached Bilibili
            return _unknown("OFFICIAL_PARTICIPATION_CLICK_UNKNOWN", exc)

        for attempt in range(_POLL_ATTEMPTS):
            try:
                text = _normalize(
                    await _read_text(panel.locator("body"), self.timeout_ms)
                )
            except Exception as exc:  # noqa: BLE001 - terminal state is uncertain
                return _unknown("OFFICIAL_PARTICIPATION_TERMINAL_READ_UNKNOWN", exc)
            terminal = classify_official_panel_text(text)
            if _DONE_RE.search(text):
                close_result = await _close_lottery_panel(
                    page,
                    timeout_ms=self.timeout_ms,
                )
                if close_result is not None:
                    return close_result
                marker_result = await ensure_activity_like_marker(
                    page,
                    timeout_ms=self.timeout_ms,
                )
                if marker_result.state is ActivityLikeMarkerState.LIKED:
                    return OfficialParticipationWriteResult(
                        OfficialParticipationOutcomeState.SUCCESS,
                        "OFFICIAL_PARTICIPATION_CONFIRMED",
                        "official participation and activity like marker are both confirmed",
                    )
                return OfficialParticipationWriteResult(
                    OfficialParticipationOutcomeState.UNKNOWN,
                    marker_result.code,
                    marker_result.message,
                )
            if terminal is not None and terminal.state is OfficialParticipationOutcomeState.UNKNOWN:
                return terminal
            if attempt + 1 < _POLL_ATTEMPTS:
                try:
                    await page.wait_for_timeout(_POLL_INTERVAL_MS)
                except Exception:
                    pass
        return OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.UNKNOWN,
            "OFFICIAL_PARTICIPATION_TERMINAL_STATE_UNKNOWN",
            "official participation click had no clear terminal confirmation",
        )


async def _read_text(locator: Any, timeout_ms: int) -> str:
    inner_text = getattr(locator, "inner_text", None)
    if not callable(inner_text):
        return ""
    return str(await inner_text(timeout=timeout_ms))


async def _read_panel_text(panel: Any, page: OfficialParticipationPage, timeout_ms: int) -> str:
    """Allow the iframe's asynchronous hydration to settle before judging it."""

    latest_text = ""
    for attempt in range(_PANEL_TEXT_ATTEMPTS):
        text = _normalize(await _read_text(panel.locator("body"), timeout_ms))
        if text:
            latest_text = text
        # A draw-time field alone is not a settled pre-click state.  The
        # already-participated label can hydrate after it, so keep polling.
        if _DONE_RE.search(text) or _SECURITY_RE.search(text):
            return text
        if attempt + 1 < _PANEL_TEXT_ATTEMPTS:
            try:
                await page.wait_for_timeout(_PANEL_TEXT_INTERVAL_MS)
            except Exception:
                pass
    return latest_text


async def _read_participation_candidates(
    panel: Any,
    page: OfficialParticipationPage,
    timeout_ms: int,
) -> list[Any]:
    """Wait briefly for asynchronously rendered participation controls."""

    for attempt in range(_PANEL_TEXT_ATTEMPTS):
        controls = panel.locator(LOTTERY_PARTICIPATION_CONTROLS_SELECTOR)
        candidates = []
        for index in range(await controls.count()):
            candidate = controls.nth(index)
            candidate_text = _normalize(await _read_text(candidate, timeout_ms))
            if _is_candidate(candidate_text):
                candidates.append(candidate)
        if candidates:
            return candidates
        if attempt + 1 < _PANEL_TEXT_ATTEMPTS:
            try:
                await page.wait_for_timeout(_PANEL_TEXT_INTERVAL_MS)
            except Exception:
                pass
    return []


async def _close_lottery_panel(
    page: OfficialParticipationPage,
    *,
    timeout_ms: int,
) -> OfficialParticipationWriteResult | None:
    """Expose the outer like toolbar before any dynamic-like click."""

    try:
        iframe_count = await page.locator(LOTTERY_IFRAME_SELECTOR).count()
    except Exception as exc:  # noqa: BLE001 - outer click is unsafe without proof
        return _unknown("OFFICIAL_LOTTERY_PANEL_CLOSE_READ_UNKNOWN", exc)
    if iframe_count == 0:
        return None
    if iframe_count != 1:
        return OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.UNKNOWN,
            "OFFICIAL_LOTTERY_PANEL_CLOSE_AMBIGUOUS",
            (
                "expected one open official lottery iframe, found "
                f"{iframe_count}; outer like was not clicked"
            ),
        )

    try:
        close_button = page.locator(LOTTERY_PANEL_CLOSE_SELECTOR)
        close_count = await close_button.count()
    except Exception as exc:  # noqa: BLE001 - outer click is unsafe without proof
        return _unknown("OFFICIAL_LOTTERY_PANEL_CLOSE_READ_UNKNOWN", exc)
    if close_count != 1:
        return OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.UNKNOWN,
            "OFFICIAL_LOTTERY_PANEL_CLOSE_NOT_UNIQUE",
            (
                "expected one official lottery popup close control, found "
                f"{close_count}; outer like was not clicked"
            ),
        )

    try:
        await close_button.click(timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - popup state is uncertain
        return _unknown("OFFICIAL_LOTTERY_PANEL_CLOSE_CLICK_UNKNOWN", exc)

    for attempt in range(_POLL_ATTEMPTS):
        try:
            iframe_count = await page.locator(LOTTERY_IFRAME_SELECTOR).count()
            close_count = await page.locator(LOTTERY_PANEL_CLOSE_SELECTOR).count()
        except Exception as exc:  # noqa: BLE001 - outer click is unsafe without proof
            return _unknown("OFFICIAL_LOTTERY_PANEL_CLOSE_TERMINAL_READ_UNKNOWN", exc)
        if iframe_count == 0 and close_count == 0:
            return None
        if attempt + 1 < _POLL_ATTEMPTS:
            try:
                await page.wait_for_timeout(_POLL_INTERVAL_MS)
            except Exception:
                pass
    return OfficialParticipationWriteResult(
        OfficialParticipationOutcomeState.UNKNOWN,
        "OFFICIAL_LOTTERY_PANEL_CLOSE_TERMINAL_UNKNOWN",
        "official lottery popup stayed open; outer like was not clicked",
    )


def _normalize(value: str) -> str:
    return "".join(value.replace("\u200b", "").replace("\ufeff", "").split())


def _is_candidate(text: str) -> bool:
    if not text or _DONE_RE.search(text):
        return False
    folded = text.casefold()
    return any(fragment.casefold() in folded for fragment in PARTICIPATION_TEXT_ALLOWLIST)


def _classify_preclick_already_participated(
    text: str,
) -> OfficialParticipationWriteResult | None:
    """Return the legacy terminal state before any participation/like click."""

    if not _DONE_RE.search(_normalize(text)):
        return None
    return OfficialParticipationWriteResult(
        OfficialParticipationOutcomeState.ALREADY_PARTICIPATED,
        "ALREADY_PARTICIPATED",
        "official lottery panel already confirms participation; no button was clicked",
    )


def classify_official_panel_text(text: str) -> OfficialParticipationWriteResult | None:
    """Classify terminal state using only the official iframe's own text."""

    normalized = _normalize(text)
    if _SECURITY_RE.search(normalized):
        return OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.UNKNOWN,
            "OFFICIAL_PARTICIPATION_SECURITY_CHALLENGE",
            "official participation requires a login, captcha, or security review",
        )
    if not _DRAW_TIME_RE.search(normalized):
        return OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.EXPIRED,
            "LOTTERY_EXPIRED",
            "official lottery panel has no draw-time field and is treated as ended",
        )
    return None


def _unknown(code: str, exc: Exception) -> OfficialParticipationWriteResult:
    return OfficialParticipationWriteResult(
        OfficialParticipationOutcomeState.UNKNOWN,
        code,
        f"official participation state is unknown: {type(exc).__name__}",
    )


def _failed(code: str, message: str) -> OfficialParticipationWriteResult:
    return OfficialParticipationWriteResult(
        OfficialParticipationOutcomeState.FAILED,
        code,
        message,
    )
