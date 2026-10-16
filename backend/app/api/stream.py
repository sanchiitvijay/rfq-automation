"""Server-sent events: live phase / progress / time left for one job, or for the whole list."""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.app import events
from backend.app.db import sessions
from backend.app.models import Job
from backend.app.services.jobs import summary

router = APIRouter(prefix="/api", tags=["events"])
HEARTBEAT_S = 15


async def _stream(request: Request, channel: str, first: dict | None) -> AsyncIterator[str]:
    yield "retry: 3000\n\n"
    if first is not None:
        yield f"data: {json.dumps(first, default=str)}\n\n"
    pubsub = events.client().pubsub()
    try:
        await pubsub.subscribe(channel)
        while not await request.is_disconnected():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=HEARTBEAT_S)
            if msg is None:
                yield ": keep-alive\n\n"
                continue
            data = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
            yield f"data: {data}\n\n"
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception:  # Redis gone: tell the client to fall back to polling
        yield 'event: error\ndata: {"detail": "live updates unavailable"}\n\n'
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass


def _sse(gen: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: uuid.UUID, request: Request) -> StreamingResponse:
    async with sessions()() as s:
        job = await s.get(Job, job_id)
        first = {"type": "snapshot", "job_id": str(job_id), "job": summary(job)} if job else None
    return _sse(_stream(request, events.job_channel(str(job_id)), first))


@router.get("/events")
async def all_events(request: Request) -> StreamingResponse:
    return _sse(_stream(request, events.JOBS_CHANNEL, None))
