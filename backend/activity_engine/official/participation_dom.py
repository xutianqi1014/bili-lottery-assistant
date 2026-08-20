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

from backend.activity_engine.shared.author_follow import (
    AuthorFollowState,
    ensure_author_follow,
)

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
RESERVATION_SELECTOR_VERSION = "reservation_participation_dom_v2-like-follow"
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
_RESERVATION_CONTROL_RE = re.compile(r"^(?:预约|已预约)$")
_RESERVATION_CARD_RE = re.compile(r"预约\s*有奖")
_RESERVATION_TERMINAL_RE = re.compile(
    r"^(?:已结束|预约已结束|预约已过期|已取消|已撤销)$"
)
_RESERVATION_REVOKED_RE = re.compile(r"^已撤销$")
_RESERVATION_WATCH_ONLY_RE = re.compile(r"^去观看$")
_RESERVATION_BUTTON_SELECTOR = ".bili-dyn-card-reserve__card button"
_RESERVATION_MARKER_SELECTOR = ".bili-dyn-card-reserve__lottery__text"
_RESERVATION_SUCCESS_RE = re.compile(r"预约成功|已参与抽奖|预约成功，已参与抽奖")
_RESERVATION_EXPIRED_RE = re.compile(r"预约已过期")


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
            # The dynamic-like marker is the cross-run participation marker
            # for both interactive and reservation lotteries.  Read it before
            # looking for any actionable reservation/lottery control so an
            # already processed reservation is skipped without another write.
            like_marker = await inspect_activity_like_marker(
                page,
                timeout_ms=self.timeout_ms,
            )
            if like_marker.state is ActivityLikeMarkerState.LIKED:
                return OfficialParticipationWriteResult(
                    OfficialParticipationOutcomeState.ALREADY_PARTICIPATED,
                    "ALREADY_PARTICIPATED_LIKED",
                    (
                        "official or reservation dynamic is already liked and is "
                        "treated as participated"
                    ),
                )
            if like_marker.state is ActivityLikeMarkerState.UNKNOWN:
                return OfficialParticipationWriteResult(
                    OfficialParticipationOutcomeState.UNKNOWN,
                    like_marker.code,
                    like_marker.message,
                )
            reservation_controls, reservation_labels = await _read_reservation_controls(
                page,
                self.timeout_ms,
            )
            if reservation_labels:
                return await _perform_reservation(
                    self.browser,
                    page,
                    reservation_controls,
                    reservation_labels,
                    self.timeout_ms,
                )
            try:
                body_text = _normalize(
                    await _read_text(page.locator("body"), self.timeout_ms)
                )
            except Exception:
                # Legacy official page fixtures may not expose a body locator;
                # the lottery-entry path remains valid without it.
                body_text = ""
            if _RESERVATION_CARD_RE.search(body_text):
                return _failed(
                    "RESERVATION_CONTROL_NOT_FOUND",
                    "reservation card was identified but no unique actionable control was found",
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


async def _read_optional_locator_text(
    page: OfficialParticipationPage,
    selector: str,
    timeout_ms: int,
) -> str:
    """Read one transient visible status node without making it required."""

    try:
        locator = page.locator(selector)
        count = int(await locator.count())
        if count <= 0:
            return ""
        first = getattr(locator, "first", None)
        candidate = first if callable(first) else locator
        visible = getattr(candidate, "is_visible", None)
        if callable(visible) and not await visible():
            return ""
        return _normalize(await _read_text(candidate, timeout_ms))
    except Exception:
        return ""


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


async def _read_reservation_controls(
    page: OfficialParticipationPage,
    timeout_ms: int,
) -> tuple[list[Any], list[str]]:
    """Find exact visible reserve-card controls, excluding comment text."""

    try:
        body_text = _normalize(await _read_text(page.locator("body"), timeout_ms))
    except Exception:
        body_text = ""
    has_card_marker = await _has_reservation_card_marker(page, body_text, timeout_ms)
    try:
        locator = page.locator(_RESERVATION_BUTTON_SELECTOR)
        total = await locator.count()
    except Exception:
        # Older official lottery page fixtures do not expose a reserve-card
        # selector; that is a normal non-reservation page, not a read error.
        return [], []
    controls: list[Any] = []
    labels: list[str] = []
    nth = getattr(locator, "nth", None)
    for index in range(total):
        if callable(nth):
            candidate = nth(index)
        elif total == 1 and index == 0:
            candidate = locator
        else:
            continue
        is_visible = getattr(candidate, "is_visible", None)
        if callable(is_visible) and not await is_visible():
            continue
        label = _normalize(await _read_text(candidate, timeout_ms))
        # A revoked live stream can remove the “预约有奖” marker.  Keep the
        # exception narrow: only the exact “已撤销” label from the scoped
        # reserve-card button is accepted without the marker.
        if (
            has_card_marker
            and (
                _RESERVATION_CONTROL_RE.fullmatch(label)
                or _RESERVATION_TERMINAL_RE.fullmatch(label)
                or _RESERVATION_WATCH_ONLY_RE.fullmatch(label)
            )
        ) or _RESERVATION_REVOKED_RE.fullmatch(label):
            controls.append(candidate)
            labels.append(label)
    return controls, labels


async def _has_reservation_card_marker(
    page: OfficialParticipationPage,
    body_text: str,
    timeout_ms: int,
) -> bool:
    try:
        marker = page.locator(_RESERVATION_MARKER_SELECTOR)
        total = await marker.count()
        nth = getattr(marker, "nth", None)
        for index in range(total):
            candidate = nth(index) if callable(nth) else marker
            visible = getattr(candidate, "is_visible", None)
            if callable(visible) and not await visible():
                continue
            text = _normalize(await _read_text(candidate, timeout_ms))
            if _RESERVATION_CARD_RE.search(text):
                return True
        if total > 0:
            return False
    except Exception:
        pass
    return bool(_RESERVATION_CARD_RE.search(body_text))


async def _perform_reservation(
    browser: OfficialParticipationBrowser,
    page: OfficialParticipationPage,
    controls: list[Any],
    labels: list[str],
    timeout_ms: int,
) -> OfficialParticipationWriteResult:
    watch_only_labels = [
        label for label in labels if _RESERVATION_WATCH_ONLY_RE.fullmatch(label)
    ]
    if watch_only_labels:
        if len(labels) != 1:
            return _failed(
                "RESERVATION_CONTROL_AMBIGUOUS",
                "reserve card exposed both a watch-only and another control",
            )
        return OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.EXPIRED,
            "RESERVATION_WATCH_ONLY_SKIPPED",
            "reservation card shows 去观看; reservation is no longer actionable and was skipped",
        )
    if any(_RESERVATION_TERMINAL_RE.fullmatch(label) for label in labels):
        return OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.EXPIRED,
            "RESERVATION_EXPIRED",
            "reservation activity explicitly ended; no reservation or like was attempted",
        )
    active_count = sum(label == "已预约" for label in labels)
    unbooked = [
        control for control, label in zip(controls, labels, strict=True) if label == "预约"
    ]
    reservation_message = "reservation control already shows 已预约; no reserve click was made"
    if active_count == 1 and not unbooked:
        reservation_confirmed = True
    else:
        reservation_confirmed = False
    if active_count or len(unbooked) != 1:
        if not reservation_confirmed:
            return _failed(
                "RESERVATION_CONTROL_AMBIGUOUS",
                "reserve card did not expose exactly one unbooked reservation control",
            )
    if not reservation_confirmed:
        button = unbooked[0]
        try:
            enabled = getattr(button, "is_enabled", None)
            if callable(enabled) and not await enabled():
                return _failed("RESERVATION_CONTROL_DISABLED", "reservation control is disabled")
            scroll = getattr(button, "scroll_into_view_if_needed", None)
            if callable(scroll):
                await scroll(timeout=timeout_ms)
            await button.click(timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001 - click outcome is uncertain
            return _unknown("RESERVATION_CLICK_UNKNOWN", exc)

        for attempt in range(_POLL_ATTEMPTS):
            try:
                latest_controls, latest_labels = await _read_reservation_controls(
                    page,
                    timeout_ms,
                )
                body_text = _normalize(await _read_text(page.locator("body"), timeout_ms))
                alert_text = await _read_optional_locator_text(
                    page,
                    '[role="alert"]',
                    timeout_ms,
                )
            except Exception as exc:  # noqa: BLE001 - terminal state is uncertain
                return _unknown("RESERVATION_TERMINAL_READ_UNKNOWN", exc)
            if _RESERVATION_EXPIRED_RE.search(f"{body_text} {alert_text}"):
                return OfficialParticipationWriteResult(
                    OfficialParticipationOutcomeState.EXPIRED,
                    "RESERVATION_EXPIRED",
                    "预约点击后页面短暂显示“预约已过期”，安全跳过且不继续点赞或关注",
                )
            if "已预约" in latest_labels or _RESERVATION_SUCCESS_RE.search(body_text):
                reservation_confirmed = True
                reservation_message = (
                    "reservation button changed to 已预约 or reported successful participation"
                )
                break
            if attempt + 1 < _POLL_ATTEMPTS:
                try:
                    await page.wait_for_timeout(_POLL_INTERVAL_MS)
                except Exception:
                    pass
    if not reservation_confirmed:
        return OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.UNKNOWN,
            "RESERVATION_TERMINAL_STATE_UNKNOWN",
            "reservation click had no clear 已预约 or success confirmation",
        )

    # Like is the participation marker.  It is intentionally confirmed while
    # the dynamic page is still open, before the follow check navigates the
    # shared browser page to the author's profile.
    marker_result = await ensure_activity_like_marker(page, timeout_ms=timeout_ms)
    if marker_result.state is not ActivityLikeMarkerState.LIKED:
        return OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.UNKNOWN,
            marker_result.code,
            (
                f"{reservation_message}; reservation dynamic like was not confirmed: "
                f"{marker_result.message}"
            ),
        )

    follow_result = await ensure_author_follow(
        browser,
        page,
        timeout_ms=timeout_ms,
    )
    if follow_result.state is not AuthorFollowState.FOLLOWING:
        return OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.UNKNOWN,
            follow_result.code,
            (
                f"{reservation_message}; dynamic like confirmed, but author follow "
                f"was not confirmed: {follow_result.message}"
            ),
        )
    return OfficialParticipationWriteResult(
        OfficialParticipationOutcomeState.SUCCESS,
        "RESERVATION_CONFIRMED",
        (
            f"{reservation_message}; dynamic like confirmed; author follow confirmed "
            f"({follow_result.code})"
        ),
    )


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
