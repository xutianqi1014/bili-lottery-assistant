"""Start the local desktop server and open its HTML console."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable

import uvicorn

from backend.api.app import create_app
from backend.config import Settings
from backend.runtime.desktop_lifecycle import DesktopLifecycle

APP_ID = "BiliLotteryAssistant"


def run_desktop_server(
    settings: Settings,
    *,
    browser_opener: Callable[[str], object] = webbrowser.open,
) -> None:
    """Run one desktop instance, or focus the HTML page of an existing one."""

    url = build_ui_url(settings.host, settings.port)
    if is_assistant_running(settings.host, settings.port):
        print(f"Bili Lottery Assistant is already running at {url}")
        browser_opener(url)
        return
    if not is_port_available(settings.host, settings.port):
        raise RuntimeError(
            f"PORT_{settings.port}_IN_USE_BY_ANOTHER_PROGRAM: "
            f"close that program before starting Bili Lottery Assistant"
        )

    lifecycle = DesktopLifecycle(enabled=True, disconnect_grace_sec=3.0)
    desktop_app = create_app(desktop_lifecycle=lifecycle)
    config = uvicorn.Config(
        desktop_app,
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
        # Windows reset connections can leave asyncio listener shutdown pending.
        # Bound connection draining so application lifespan cleanup still runs.
        timeout_graceful_shutdown=5,

    )
    server = uvicorn.Server(config)
    lifecycle.set_shutdown_callback(lambda: _request_shutdown(server))

    stop_waiting = threading.Event()
    opener = threading.Thread(
        target=_open_when_listening,
        args=(settings.host, settings.port, url, stop_waiting, browser_opener),
        name="desktop-browser-opener",
        daemon=True,
    )
    opener.start()
    try:
        server.run()
    finally:
        stop_waiting.set()
        opener.join(timeout=1.0)


def build_ui_url(host: str, port: int) -> str:
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port}/"


def is_assistant_running(host: str, port: int, *, timeout_sec: float = 0.5) -> bool:
    """Only recognize this application; never take over an unrelated listener."""

    url = f"{build_ui_url(host, port)}api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as response:  # noqa: S310
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return False
    return payload.get("ok") is True and payload.get("appName") == APP_ID


def is_port_available(host: str, port: int) -> bool:
    bind_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((bind_host, port))
    except OSError:
        return False
    return True


def _open_when_listening(
    host: str,
    port: int,
    url: str,
    stop_waiting: threading.Event,
    browser_opener: Callable[[str], object],
) -> None:
    connect_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline and not stop_waiting.wait(0.1):
        try:
            with socket.create_connection((connect_host, port), timeout=0.25):
                browser_opener(url)
                return
        except OSError:
            continue


def _request_shutdown(server: uvicorn.Server) -> None:
    print("HTML console closed; stopping local service and releasing its port.")
    server.should_exit = True
