"""Private WebSocket used to tie the desktop process to its HTML pages."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from backend.api.dependencies import get_state

DESKTOP_SUBPROTOCOL = "bili-lottery-desktop"

router = APIRouter(tags=["desktop-runtime"])


@router.websocket("/api/desktop/lifecycle")
async def desktop_lifecycle(websocket: WebSocket) -> None:
    state = get_state(websocket)
    protocols = _requested_protocols(websocket)
    supplied_token = next((item for item in protocols if item != DESKTOP_SUBPROTOCOL), None)
    if (
        not state.desktop_lifecycle.enabled
        or DESKTOP_SUBPROTOCOL not in protocols
        or supplied_token is None
        or not secrets.compare_digest(supplied_token, state.csrf_token)
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    client_id = secrets.token_urlsafe(18)
    await websocket.accept(subprotocol=DESKTOP_SUBPROTOCOL)
    await state.desktop_lifecycle.attach(client_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await state.desktop_lifecycle.detach(client_id)


def _requested_protocols(websocket: WebSocket) -> tuple[str, ...]:
    value = websocket.headers.get("sec-websocket-protocol", "")
    return tuple(item.strip() for item in value.split(",") if item.strip())
