"""Track local HTML clients and stop the desktop server after they close.

The browser page keeps one WebSocket open for its whole lifetime. A socket is
more reliable than JavaScript timers for detecting a closed or background tab.
The short disconnect grace period lets a normal page refresh reconnect without
stopping the desktop process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress


class DesktopLifecycle:
    """Own the connection count and the delayed desktop shutdown request."""

    def __init__(self, *, enabled: bool, disconnect_grace_sec: float = 3.0) -> None:
        if disconnect_grace_sec < 0:
            raise ValueError("DESKTOP_DISCONNECT_GRACE_MUST_BE_NON_NEGATIVE")
        self.enabled = enabled
        self.disconnect_grace_sec = disconnect_grace_sec
        self._clients: set[str] = set()
        self._has_connected = False
        self._shutdown_requested = False
        self._shutdown_callback: Callable[[], None] | None = None
        self._pending_shutdown: asyncio.Task[None] | None = None

    @property
    def active_clients(self) -> int:
        return len(self._clients)

    @property
    def has_connected(self) -> bool:
        return self._has_connected

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    def set_shutdown_callback(self, callback: Callable[[], None]) -> None:
        self._shutdown_callback = callback

    async def attach(self, client_id: str) -> None:
        """Register one HTML page and cancel any refresh-grace shutdown."""

        if not self.enabled:
            return
        self._clients.add(client_id)
        self._has_connected = True
        task = self._pending_shutdown
        self._pending_shutdown = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def detach(self, client_id: str) -> None:
        """Unregister a page and start shutdown grace for the final page."""

        if not self.enabled:
            return
        self._clients.discard(client_id)
        if (
            self._clients
            or not self._has_connected
            or self._shutdown_requested
            or self._pending_shutdown is not None
        ):
            return
        self._pending_shutdown = asyncio.create_task(
            self._shutdown_after_grace(),
            name="desktop-lifecycle-shutdown",
        )

    async def close(self) -> None:
        """Cancel lifecycle bookkeeping during normal application shutdown."""

        task = self._pending_shutdown
        self._pending_shutdown = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._clients.clear()

    async def _shutdown_after_grace(self) -> None:
        try:
            await asyncio.sleep(self.disconnect_grace_sec)
            if self._clients or self._shutdown_requested:
                return
            callback = self._shutdown_callback
            if callback is None:
                return
            self._shutdown_requested = True
            callback()
        finally:
            current = asyncio.current_task()
            if self._pending_shutdown is current:
                self._pending_shutdown = None
