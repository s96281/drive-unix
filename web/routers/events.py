"""Global Server-Sent Events (SSE) router (/api/events)."""

from __future__ import annotations

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from web.events import broadcaster

router = APIRouter(prefix="/api/events", tags=["Events"])


@router.get("")
async def stream_global_events(
    last_event_id: int | None = Query(None, description="Last received sequence ID"),
    last_event_id_header: str | None = Header(None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Stream all application events (task.update, task.log, log, system, heartbeat)."""
    # Prefer header if present and valid int, otherwise query param
    target_id = last_event_id
    if last_event_id_header is not None:
        try:
            target_id = int(last_event_id_header)
        except ValueError:
            pass

    return StreamingResponse(
        broadcaster.stream(target_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
