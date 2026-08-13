import asyncio
from contextlib import suppress
from typing import Any

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from backend.config import Settings


class BrowserUnavailable(RuntimeError):
    """The visible browser cannot be started or used."""


class BrowserManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._unassigned_page: Page | None = None
        self._page: Page | None = None
        self._login_page: Page | None = None
        # HTTP requests and background jobs can reach the browser manager at
        # the same time. Serializing page allocation is what makes rapid,
        # repeated "open login" clicks idempotent.
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return self._context is not None

    async def start(self) -> None:
        async with self._lock:
            await self._ensure_context_locked()

    async def open(self, url: str) -> Page:
        async with self._lock:
            for attempt in range(2):
                context = await self._ensure_context_locked()
                page = self._page
                if page is None or page.is_closed():
                    page = await self._allocate_page_locked(context)
                    self._page = page
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    return page
                except Exception:
                    if attempt == 0 and await self._target_was_closed_locked(page, context):
                        continue
                    raise
        raise BrowserUnavailable("BROWSER_PAGE_NOT_AVAILABLE")

    async def login_page(self) -> Page:
        async with self._lock:
            for attempt in range(2):
                context = await self._ensure_context_locked()
                page = self._login_page
                if page is not None and not page.is_closed():
                    try:
                        await page.bring_to_front()
                        return page
                    except Exception:
                        if attempt == 0 and await self._target_was_closed_locked(page, context):
                            continue
                        raise

                page = await self._allocate_page_locked(context)
                self._login_page = page
                try:
                    await page.goto(
                        "https://passport.bilibili.com/login",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    await page.bring_to_front()
                    return page
                except Exception:
                    if attempt == 0 and await self._target_was_closed_locked(page, context):
                        continue
                    raise
        raise BrowserUnavailable("BROWSER_LOGIN_PAGE_NOT_AVAILABLE")

    async def close(self) -> None:
        async with self._lock:
            context = self._context
            playwright = self._playwright
            self._clear_context_references(context)
            self._playwright = None
            if context is not None:
                with suppress(Exception):
                    await context.close()
            if playwright is not None:
                with suppress(Exception):
                    await playwright.stop()

    async def _ensure_context_locked(self) -> BrowserContext:
        context = self._context
        if context is not None and await self._context_is_alive(context):
            return context
        if context is not None:
            self._clear_context_references(context)
            with suppress(Exception):
                await context.close()

        try:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            launch_options: dict[str, Any] = {
                "user_data_dir": str(self.settings.browser_profile_path),
                "headless": self.settings.browser_headless,
                "viewport": {"width": 1440, "height": 900},
                "locale": "zh-CN",
            }
            if self.settings.browser_channel:
                launch_options["channel"] = self.settings.browser_channel
            context = await self._playwright.chromium.launch_persistent_context(
                **launch_options
            )
            self._context = context
            context.on("close", lambda _closed: self._on_context_closed(context))
            initial_pages = list(context.pages)
            self._unassigned_page = initial_pages[0] if initial_pages else None
            for page in initial_pages:
                self._watch_page(page)
            return context
        except Exception as exc:
            await self._discard_failed_start_locked()
            raise BrowserUnavailable(f"BROWSER_START_FAILED:{type(exc).__name__}") from exc

    async def _allocate_page_locked(self, context: BrowserContext) -> Page:
        page = self._unassigned_page
        self._unassigned_page = None
        if page is None or page.is_closed():
            page = await context.new_page()
            self._watch_page(page)
        return page

    async def _target_was_closed_locked(
        self,
        page: Page,
        context: BrowserContext,
    ) -> bool:
        page_closed = page.is_closed()
        context_closed = not await self._context_is_alive(context)
        if not page_closed and not context_closed:
            return False
        self._on_page_closed(page)
        if context_closed:
            self._clear_context_references(context)
        return True

    @staticmethod
    async def _context_is_alive(context: BrowserContext) -> bool:
        try:
            await context.cookies()
        except Exception:
            return False
        return True

    def _watch_page(self, page: Page) -> None:
        page.on("close", lambda _closed: self._on_page_closed(page))

    def _on_page_closed(self, page: Page) -> None:
        if self._unassigned_page is page:
            self._unassigned_page = None
        if self._page is page:
            self._page = None
        if self._login_page is page:
            self._login_page = None

    def _on_context_closed(self, context: BrowserContext) -> None:
        self._clear_context_references(context)

    def _clear_context_references(self, context: BrowserContext | None) -> None:
        if context is not None and self._context is not context:
            return
        self._context = None
        self._unassigned_page = None
        self._page = None
        self._login_page = None

    async def _discard_failed_start_locked(self) -> None:
        context = self._context
        playwright = self._playwright
        self._clear_context_references(context)
        self._playwright = None
        if context is not None:
            with suppress(Exception):
                await context.close()
        if playwright is not None:
            with suppress(Exception):
                await playwright.stop()
