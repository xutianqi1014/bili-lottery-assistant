import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.routes.desktop as desktop_route
from backend.runtime import DesktopLifecycle


@pytest.mark.asyncio
async def test_final_page_disconnect_requests_shutdown_after_grace() -> None:
    lifecycle = DesktopLifecycle(enabled=True, disconnect_grace_sec=0.01)
    shutdown = asyncio.Event()
    lifecycle.set_shutdown_callback(shutdown.set)

    await lifecycle.attach("page-one")
    await lifecycle.detach("page-one")

    await asyncio.wait_for(shutdown.wait(), timeout=0.2)
    assert lifecycle.shutdown_requested is True


@pytest.mark.asyncio
async def test_refresh_reconnect_cancels_pending_shutdown() -> None:
    lifecycle = DesktopLifecycle(enabled=True, disconnect_grace_sec=0.05)
    shutdown = asyncio.Event()
    lifecycle.set_shutdown_callback(shutdown.set)

    await lifecycle.attach("old-page")
    await lifecycle.detach("old-page")
    await asyncio.sleep(0.01)
    await lifecycle.attach("refreshed-page")
    await asyncio.sleep(0.06)

    assert shutdown.is_set() is False
    assert lifecycle.active_clients == 1
    await lifecycle.detach("refreshed-page")
    await asyncio.wait_for(shutdown.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_one_of_multiple_pages_does_not_stop_server() -> None:
    lifecycle = DesktopLifecycle(enabled=True, disconnect_grace_sec=0.01)
    shutdown = asyncio.Event()
    lifecycle.set_shutdown_callback(shutdown.set)

    await lifecycle.attach("page-one")
    await lifecycle.attach("page-two")
    await lifecycle.detach("page-one")
    await asyncio.sleep(0.03)

    assert shutdown.is_set() is False
    assert lifecycle.active_clients == 1
    await lifecycle.close()


@pytest.mark.asyncio
async def test_disabled_lifecycle_never_requests_shutdown() -> None:
    lifecycle = DesktopLifecycle(enabled=False, disconnect_grace_sec=0)
    shutdown = asyncio.Event()
    lifecycle.set_shutdown_callback(shutdown.set)

    await lifecycle.attach("page")
    await lifecycle.detach("page")
    await asyncio.sleep(0)

    assert shutdown.is_set() is False
    assert lifecycle.has_connected is False


def test_authenticated_websocket_drives_desktop_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = DesktopLifecycle(enabled=True, disconnect_grace_sec=0.01)
    shutdown = threading.Event()
    lifecycle.set_shutdown_callback(shutdown.set)
    state = SimpleNamespace(desktop_lifecycle=lifecycle, csrf_token="test-token")
    monkeypatch.setattr(desktop_route, "get_state", lambda _socket: state)
    app = FastAPI()
    app.include_router(desktop_route.router)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/desktop/lifecycle",
            subprotocols=[desktop_route.DESKTOP_SUBPROTOCOL, "test-token"],
        ) as socket:
            assert socket.accepted_subprotocol == desktop_route.DESKTOP_SUBPROTOCOL
            assert lifecycle.active_clients == 1
        assert shutdown.wait(timeout=0.2) is True

    assert lifecycle.shutdown_requested is True
