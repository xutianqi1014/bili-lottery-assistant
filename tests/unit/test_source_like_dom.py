import pytest

from backend.source_adapters.lottery_toolman.source_like import SourceLikeOutcomeState
from backend.source_adapters.lottery_toolman.source_like_dom import (
    SOURCE_LIKE_ACTIVE_SELECTOR,
    SOURCE_LIKE_SELECTOR,
    DomSourceLikeTransport,
)


class _FakeLocator:
    def __init__(
        self,
        count_value: int,
        on_click: object | None = None,
        click_error: Exception | None = None,
    ) -> None:
        self.count_value = count_value
        self.on_click = on_click
        self.click_error = click_error
        self.clicks = 0

    async def count(self) -> int:
        return self.count_value

    async def click(self, *, timeout: int) -> None:
        del timeout
        if self.click_error is not None:
            raise self.click_error
        self.clicks += 1
        if callable(self.on_click):
            self.on_click()


class _FakePage:
    def __init__(
        self,
        *,
        active: bool = False,
        button_count: int = 1,
        click_error: Exception | None = None,
        active_wait_error: Exception | None = None,
    ) -> None:
        self.active = active
        self.active_wait_error = active_wait_error
        self.waited: list[str] = []
        self.button = _FakeLocator(
            button_count,
            on_click=self._activate,
            click_error=click_error,
        )

    def _activate(self) -> None:
        self.active = True

    async def wait_for_selector(self, selector: str, *, timeout: int) -> None:
        del timeout
        self.waited.append(selector)
        if selector == SOURCE_LIKE_ACTIVE_SELECTOR:
            if self.active_wait_error is not None:
                raise self.active_wait_error
            if not self.active:
                raise TimeoutError("active selector not found")

    def locator(self, selector: str) -> _FakeLocator:
        if selector == SOURCE_LIKE_ACTIVE_SELECTOR:
            return _FakeLocator(1 if self.active else 0)
        if selector == SOURCE_LIKE_SELECTOR:
            return self.button
        raise AssertionError(f"unexpected selector: {selector}")


class _FakeBrowser:
    def __init__(self, page: _FakePage | None = None, error: Exception | None = None) -> None:
        self.page = page
        self.error = error
        self.opened: list[str] = []

    async def open(self, url: str) -> _FakePage:
        self.opened.append(url)
        if self.error is not None:
            raise self.error
        assert self.page is not None
        return self.page


@pytest.mark.asyncio
async def test_dom_transport_returns_already_done_without_clicking_active_source() -> None:
    page = _FakePage(active=True)
    result = await DomSourceLikeTransport(_FakeBrowser(page)).perform(
        target_url="https://www.bilibili.com/read/cv123",
        payload={},
    )

    assert result.state is SourceLikeOutcomeState.ALREADY_DONE
    assert result.code == "SOURCE_ALREADY_LIKED"
    assert page.button.clicks == 0
    assert page.waited == [SOURCE_LIKE_SELECTOR]


@pytest.mark.asyncio
async def test_dom_transport_clicks_once_and_confirms_active_terminal_state() -> None:
    page = _FakePage()
    result = await DomSourceLikeTransport(_FakeBrowser(page)).perform(
        target_url="https://www.bilibili.com/read/cv123",
        payload={"sourceArticleId": "cv123"},
    )

    assert result.state is SourceLikeOutcomeState.SUCCESS
    assert result.code == "SOURCE_LIKE_CONFIRMED"
    assert page.button.clicks == 1
    assert page.waited == [SOURCE_LIKE_SELECTOR, SOURCE_LIKE_ACTIVE_SELECTOR]


@pytest.mark.asyncio
async def test_dom_transport_marks_click_failure_unknown_without_retry_signal() -> None:
    page = _FakePage(click_error=TimeoutError("click timed out"))
    result = await DomSourceLikeTransport(_FakeBrowser(page)).perform(
        target_url="https://www.bilibili.com/read/cv123",
        payload={},
    )

    assert result.state is SourceLikeOutcomeState.UNKNOWN
    assert result.code == "SOURCE_LIKE_CLICK_UNKNOWN"
    assert page.waited == [SOURCE_LIKE_SELECTOR]


@pytest.mark.asyncio
async def test_dom_transport_marks_missing_terminal_state_unknown() -> None:
    page = _FakePage(active_wait_error=TimeoutError("terminal state timed out"))
    result = await DomSourceLikeTransport(_FakeBrowser(page)).perform(
        target_url="https://www.bilibili.com/read/cv123",
        payload={},
    )

    assert result.state is SourceLikeOutcomeState.UNKNOWN
    assert result.code == "SOURCE_LIKE_TERMINAL_STATE_UNKNOWN"
    assert page.button.clicks == 1


@pytest.mark.asyncio
async def test_dom_transport_rejects_ambiguous_button_without_click() -> None:
    page = _FakePage(button_count=2)
    result = await DomSourceLikeTransport(_FakeBrowser(page)).perform(
        target_url="https://www.bilibili.com/read/cv123",
        payload={},
    )

    assert result.state is SourceLikeOutcomeState.FAILED
    assert result.code == "SOURCE_LIKE_BUTTON_AMBIGUOUS"
    assert page.button.clicks == 0


@pytest.mark.asyncio
async def test_dom_transport_marks_page_read_failure_unknown() -> None:
    result = await DomSourceLikeTransport(
        _FakeBrowser(error=RuntimeError("browser unavailable"))
    ).perform(
        target_url="https://www.bilibili.com/read/cv123",
        payload={},
    )

    assert result.state is SourceLikeOutcomeState.UNKNOWN
    assert result.code == "SOURCE_LIKE_PAGE_READ_UNKNOWN"
