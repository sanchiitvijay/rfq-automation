"""Shared app state (queue pool, cache) and request dependencies."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db import get_session
from backend.app.models import Job


def queue(request: Request) -> Any:
    pool = getattr(request.app.state, "queue", None)
    if pool is None:
        raise HTTPException(503, "The job queue (Redis) is not available. Start Redis and try again.")
    return pool


class _NoQueue:
    async def enqueue_job(self, *a: Any, **k: Any) -> None:
        raise ConnectionError("job queue not connected")


def queue_or_none(request: Request) -> Any:
    """For creating jobs: even without a queue the job is saved and picked up later."""
    return getattr(request.app.state, "queue", None) or _NoQueue()


def cache(request: Request) -> Any:
    return request.app.state.cache


async def load_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Job:
    job = await session.get(Job, job_id, options=[selectinload(Job.items), selectinload(Job.events),
                                                  selectinload(Job.edits), selectinload(Job.sends)])
    if job is None:
        raise HTTPException(404, "job not found")
    return job
