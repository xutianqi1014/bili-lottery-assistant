import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from backend.browser.manager import BrowserManager
from backend.config import Settings


class FakePage:
    def __init__(self, context: "FakeContext") -> None:
        self.context = context
        self.closed = False
        self.goto_urls: list[str] = []
        self.bring_to_front_count = 0
        self._close_handlers: list[Callable[[FakePage], None]] = []

    def is_closed(self) -> bool:
        return self.closed

    def on(self, event: str, handler: Callable[["FakePage"], None]) -> None:
        if event == "close":
            self._close_handlers.append(handler)

    async def goto(self, url: str, **_kwargs: Any) -> None:
        if self.closed or self.context.closed:
            raise RuntimeError("TARGET_CLOSED")
        self.goto_urls.append(url)

    async def bring_to_front(self) -> None:
        if self.closed or self.context.closed:
            raise RuntimeError("TARGET_CLOSED")
        self.bring_to_front_count += 1

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for handler in tuple(self._close_handlers):
            handler(self)
        if self.context.close_when_last_page and all(page.closed for page in self.context.pages):
            self.context.emit_close()


class FakeContext:
    def __init__(self, *, close_when_last_page: bool = False) -> None:
        self.closed = False
        self.close_when_last_page = close_when_last_page
        self.pages: list[FakePage] = [FakePage(self)]
        self.new_page_count = 0
        self._close_handlers: list[Callable[[FakeContext], None]] = []

    def on(self, event: str, handler: Callable[["FakeContext"], None]) -> None:
        if event == "close":
            self._close_handlers.append(handler)

    async def cookies(self) -> list[object]:
        if self.closed:
            raise RuntimeError("CONTEXT_CLOSED")
        return []

    async def new_page(self) -> FakePage:
        if self.closed:
            raise RuntimeError("CONTEXT_CLOSED")
        self.new_page_count += 1
        page = FakePage(self)
        self.pages.append(page)
        return page

    async def close(self) -> None:
        if self.closed:
            return
        for page in tuple(self.pages):
            await page.close()
        self.emit_close()

    def emit_close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for handler in tuple(self._close_handlers):
            handler(self)


class FakeChromium:
    def __init__(self, *, close_when_last_page: bool = False) -> None:
        self.close_when_last_page = close_when_last_page
        self.contexts: list[FakeContext] = []

    async def launch_persistent_context(self, **_kwargs: Any) -> FakeContext:
        context = FakeContext(close_when_last_page=self.close_when_last_page)
        self.contexts.append(context)
        return context


class FakePlaywright:
    def __init__(self, *, close_when_last_page: bool = False) -> None:
        self.chromium = FakeChromium(close_when_last_page=close_when_last_page)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def manager_with_fake(
    tmp_path: Path,
    *,
    close_when_last_page: bool = False,
) -> tuple[BrowserManager, FakePlaywright]:
    manager = BrowserManager(
        Settings(browser_profile_dir=tmp_path / "browser", browser_channel="")
    )
    fake = FakePlaywright(close_when_last_page=close_when_last_page)
    manager._playwright = fake  # type: ignore[assignment]
    return manager, fake


@pytest.mark.asyncio
async def test_repeated_login_click_focuses_one_existing_page(tmp_path: Path) -> None:
    manager, fake = manager_with_fake(tmp_path)

    first = await manager.login_page()
    second = await manager.login_page()

    assert first is second
    assert len(fake.chromium.contexts) == 1
    assert fake.chromium.contexts[0].new_page_count == 0
    assert first.goto_urls == ["https://passport.bilibili.com/login"]
    assert first.bring_to_front_count == 2


@pytest.mark.asyncio
async def test_closed_login_page_can_be_opened_again_in_same_context(tmp_path: Path) -> None:
    manager, fake = manager_with_fake(tmp_path)
    first = await manager.login_page()

    await first.close()
    second = await manager.login_page()

    assert second is not first
    assert len(fake.chromium.contexts) == 1
    assert fake.chromium.contexts[0].new_page_count == 1
    assert second.goto_urls == ["https://passport.bilibili.com/login"]


@pytest.mark.asyncio
async def test_closed_last_login_page_restarts_closed_context(tmp_path: Path) -> None:
    manager, fake = manager_with_fake(tmp_path, close_when_last_page=True)
    first = await manager.login_page()

    await first.close()
    second = await manager.login_page()

    assert second is not first
    assert len(fake.chromium.contexts) == 2
    assert second.context is fake.chromium.contexts[1]


@pytest.mark.asyncio
async def test_concurrent_login_requests_do_not_create_duplicate_pages(tmp_path: Path) -> None:
    manager, fake = manager_with_fake(tmp_path)

    pages = await asyncio.gather(*(manager.login_page() for _ in range(5)))

    assert len({id(page) for page in pages}) == 1
    assert len(fake.chromium.contexts) == 1
    assert len(fake.chromium.contexts[0].pages) == 1


@pytest.mark.asyncio
async def test_login_page_is_not_reused_as_automation_page(tmp_path: Path) -> None:
    manager, fake = manager_with_fake(tmp_path)
    login = await manager.login_page()

    automation = await manager.open("https://www.bilibili.com/opus/123")
    focused_login = await manager.login_page()

    assert automation is not login
    assert focused_login is login
    assert len(fake.chromium.contexts[0].pages) == 2
    assert automation.goto_urls == ["https://www.bilibili.com/opus/123"]
