"""Live updates over Redis pub/sub: one channel per job plus a 'jobs' channel for the list view."""
from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as redis

from backend.app.settings import get_settings

log = logging.getLogger(__name__)
JOBS_CHANNEL = "rfq:jobs"
_client: redis.Redis | None = None


def job_channel(job_id: str) -> str:
    return f"rfq:job:{job_id}"


def client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
    return _client


async def publish(job_id: str, event: dict[str, Any]) -> None:
    """Best effort: a Redis hiccup must never fail the job itself."""
    payload = json.dumps({"job_id": job_id, **event}, default=str)
    try:
        await client().publish(job_channel(job_id), payload)
        await client().publish(JOBS_CHANNEL, payload)
    except Exception as e:
        log.warning("publish failed: %s", e)


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
