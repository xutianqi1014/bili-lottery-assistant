import socket
from types import SimpleNamespace
from typing import Any

import pytest

import backend.runtime.desktop_server as desktop_server
from backend.runtime.desktop_server import build_ui_url, is_port_available


def test_default_loopback_url_is_stable() -> None:
    assert build_ui_url("127.0.0.1", 8787) == "http://127.0.0.1:8787/"
    assert build_ui_url("0.0.0.0", 8787) == "http://127.0.0.1:8787/"


def test_port_probe_does_not_modify_an_existing_listener() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        assert is_port_available("127.0.0.1", port) is False

    assert is_port_available("127.0.0.1", port) is True


def test_second_launcher_opens_existing_assistant_without_starting_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(desktop_server, "is_assistant_running", lambda _host, _port: True)
    monkeypatch.setattr(
        desktop_server,
        "is_port_available",
        lambda _host, _port: pytest.fail("port probe must not run"),
    )
    settings = SimpleNamespace(host="127.0.0.1", port=8787)

    desktop_server.run_desktop_server(settings, browser_opener=opened.append)  # type: ignore[arg-type]

    assert opened == ["http://127.0.0.1:8787/"]


def test_launcher_refuses_to_take_over_an_unrelated_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(desktop_server, "is_assistant_running", lambda _host, _port: False)
    monkeypatch.setattr(desktop_server, "is_port_available", lambda _host, _port: False)
    settings = SimpleNamespace(host="127.0.0.1", port=8787)

    with pytest.raises(RuntimeError, match="PORT_8787_IN_USE_BY_ANOTHER_PROGRAM"):
        desktop_server.run_desktop_server(settings)  # type: ignore[arg-type]


def test_health_probe_recognizes_only_this_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok":true,"appName":"BiliLotteryAssistant"}'

    monkeypatch.setattr(desktop_server.urllib.request, "urlopen", lambda *_a, **_k: Response())

    assert desktop_server.is_assistant_running("127.0.0.1", 8787) is True
