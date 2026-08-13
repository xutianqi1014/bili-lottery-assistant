import pytest

from backend.activity_engine.official.activity_like_marker import (
    ACTIVITY_LIKE_ACTIVE_SELECTOR,
    ACTIVITY_LIKE_SELECTOR,
    ActivityLikeMarkerState,
    ensure_activity_like_marker,
    inspect_activity_like_marker,
)


class _Locator:
    def __init__(self, page, selector: str) -> None:
        self.page = page
        self.selector = selector

    async def count(self) -> int:
        if self.selector == ACTIVITY_LIKE_SELECTOR:
            return self.page.like_count
        return self.page.active_count

    async def click(self, *, timeout: int, force: bool = False) -> None:
        del timeout
        assert force is False
        self.page.clicks += 1
        if self.page.activate_after_click:
            self.page.active_count = 1


class _Page:
    def __init__(
        self,
        *,
        like_count: int = 1,
        active_count: int = 0,
        activate_after_click: bool = True,
    ) -> None:
        self.like_count = like_count
        self.active_count = active_count
        self.activate_after_click = activate_after_click
        self.clicks = 0

    async def wait_for_selector(self, selector: str, *, timeout: int) -> None:
        del timeout
        assert selector == ACTIVITY_LIKE_SELECTOR
        if self.like_count == 0:
            raise TimeoutError

    def locator(self, selector: str) -> _Locator:
        assert selector in {ACTIVITY_LIKE_SELECTOR, ACTIVITY_LIKE_ACTIVE_SELECTOR}
        return _Locator(self, selector)

    async def wait_for_timeout(self, timeout: int) -> None:
        del timeout


@pytest.mark.asyncio
async def test_liked_marker_is_read_without_click() -> None:
    page = _Page(active_count=1)

    result = await inspect_activity_like_marker(page, timeout_ms=100)

    assert result.state is ActivityLikeMarkerState.LIKED
    assert result.code == "OFFICIAL_ACTIVITY_ALREADY_LIKED"
    assert page.clicks == 0


@pytest.mark.asyncio
async def test_unliked_marker_is_clicked_once_and_confirmed() -> None:
    page = _Page()

    result = await ensure_activity_like_marker(page, timeout_ms=100)

    assert result.state is ActivityLikeMarkerState.LIKED
    assert result.code == "OFFICIAL_ACTIVITY_LIKE_CONFIRMED"
    assert result.click_attempted is True
    assert page.clicks == 1


@pytest.mark.asyncio
async def test_missing_or_ambiguous_marker_is_unknown_without_click() -> None:
    missing = _Page(like_count=0)
    ambiguous = _Page(like_count=2)

    missing_result = await inspect_activity_like_marker(missing, timeout_ms=100)
    ambiguous_result = await inspect_activity_like_marker(ambiguous, timeout_ms=100)

    assert missing_result.state is ActivityLikeMarkerState.UNKNOWN
    assert missing_result.code == "OFFICIAL_ACTIVITY_LIKE_READ_UNKNOWN"
    assert ambiguous_result.state is ActivityLikeMarkerState.UNKNOWN
    assert ambiguous_result.code == "OFFICIAL_ACTIVITY_LIKE_MARKER_AMBIGUOUS"
    assert missing.clicks == ambiguous.clicks == 0
