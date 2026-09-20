"""Desktop exit must reach application cleanup even if a listener never drains."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import uvicorn

from backend.runtime import desktop_server


def test_stalled_listener_shutdown_still_reaches_application_cleanup(monkeypatch):
    listener = SimpleNamespace(close=lambda: None)
    cleaned = []

    async def stalled():
        await asyncio.Event().wait()

    listener.wait_closed = stalled
    real_server_class = uvicorn.Server

    class StartedServer(real_server_class):
        def run(self, sockets=None):
            # Exercise the launcher's real configuration and Uvicorn shutdown,
            # with only the OS listener replaced by a permanently stalled one.
            assert self.config.timeout_graceful_shutdown == 5
            self.servers = [listener]
            self.lifespan = SimpleNamespace(
                shutdown=AsyncMock(side_effect=lambda: cleaned.append(1))
            )

            async def close():
                await asyncio.wait_for(self.shutdown(), timeout=7)

            asyncio.run(close())

    monkeypatch.setattr(desktop_server, "is_assistant_running", lambda *_: False)
    monkeypatch.setattr(desktop_server, "is_port_available", lambda *_: True)
    monkeypatch.setattr(desktop_server, "_open_when_listening", lambda *_: None)
    monkeypatch.setattr(desktop_server.uvicorn, "Server", StartedServer)
    desktop_server.run_desktop_server(
        SimpleNamespace(host="127.0.0.1", port=8787), browser_opener=lambda _: None
    )
    assert cleaned == [1]
