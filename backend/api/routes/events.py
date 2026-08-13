import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.api.dependencies import get_state

router = APIRouter(tags=["events"])


@router.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    state = get_state(request)
    queue = state.events.subscribe()

    async def stream() -> AsyncGenerator[str, None]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    payload = json.dumps(event.data, ensure_ascii=False)
                    yield f"event: {event.name}\ndata: {payload}\n\n"
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            state.events.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")
