"""Shared cache + cross-worker coordination for ferguson.com.

RedisCache is used by the backend workers; MemoryCache is the fallback for the CLI or when Redis is
down, so the flow never depends on Redis being available.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Protocol

log = logging.getLogger(__name__)

LOOKUP_TTL = 24 * 3600
PDF_TTL = 7 * 24 * 3600
LLM_TTL = 7 * 24 * 3600
BLOCK_COOLDOWN = 10 * 60
BLOCKS_BEFORE_COOLDOWN = 3


class Cache(Protocol):
    async def get_json(self, key: str) -> Any | None: ...
    async def set_json(self, key: str, value: Any, ttl: int) -> None: ...
    async def get_bytes(self, key: str) -> bytes | None: ...
    async def set_bytes(self, key: str, value: bytes, ttl: int) -> None: ...
    async def incr_window(self, key: str, window: int) -> int: ...
    async def set_flag(self, key: str, ttl: int) -> None: ...
    async def has_flag(self, key: str) -> bool: ...
    def slot(self, name: str, slots: int, min_gap_s: float) -> Any: ...
    async def rate(self, name: str, limit: int, window_s: float = 60.0) -> float: ...


class MemoryCache:
    """In-process cache with the same interface (single process only)."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._last: dict[str, float] = {}
        self._gap_lock = asyncio.Lock()
        self._hits: dict[str, list[float]] = {}
        self._rate_lock = asyncio.Lock()

    def _get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if not item or item[0] < time.time():
            self._data.pop(key, None)
            return None
        return item[1]

    async def get_json(self, key: str) -> Any | None:
        return self._get(key)

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        self._data[key] = (time.time() + ttl, value)

    async def get_bytes(self, key: str) -> bytes | None:
        return self._get(key)

    async def set_bytes(self, key: str, value: bytes, ttl: int) -> None:
        self._data[key] = (time.time() + ttl, value)

    async def incr_window(self, key: str, window: int) -> int:
        count = (self._get(key) or 0) + 1
        self._data[key] = (time.time() + window, count)
        return count

    async def set_flag(self, key: str, ttl: int) -> None:
        self._data[key] = (time.time() + ttl, True)

    async def has_flag(self, key: str) -> bool:
        return bool(self._get(key))

    @asynccontextmanager
    async def slot(self, name: str, slots: int, min_gap_s: float) -> AsyncIterator[None]:
        sem = self._sems.setdefault(name, asyncio.Semaphore(slots))
        async with sem:
            async with self._gap_lock:
                wait = self._last.get(name, 0) + min_gap_s - time.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last[name] = time.time()
            yield


    async def rate(self, name: str, limit: int, window_s: float = 60.0) -> float:
        """Waits until one more call fits in the sliding window; returns the seconds waited."""
        waited = 0.0
        while True:
            async with self._rate_lock:
                now = time.time()
                hits = [h for h in self._hits.get(name, []) if h > now - window_s]
                if len(hits) < limit:
                    hits.append(now)
                    self._hits[name] = hits
                    return waited
                wait = hits[0] + window_s - now
                self._hits[name] = hits
            await asyncio.sleep(wait + 0.05)
            waited += wait + 0.05


# Sliding-window limiter: one atomic step per call, shared by every worker.
_RATE_LUA = """
local key, now, window, limit, member = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
if redis.call('ZCARD', key) < limit then
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, window)
  return 0
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
return math.max(1, math.floor(tonumber(oldest[2]) + window - now))
"""


class RedisCache:
    """Redis-backed cache; slots/min-gap are global across every worker process."""

    def __init__(self, client: Any) -> None:
        self.r = client

    async def get_json(self, key: str) -> Any | None:
        raw = await self.r.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        await self.r.set(key, json.dumps(value), ex=ttl)

    async def get_bytes(self, key: str) -> bytes | None:
        return await self.r.get(key)

    async def set_bytes(self, key: str, value: bytes, ttl: int) -> None:
        await self.r.set(key, value, ex=ttl)

    async def incr_window(self, key: str, window: int) -> int:
        count = await self.r.incr(key)
        if count == 1:
            await self.r.expire(key, window)
        return int(count)

    async def set_flag(self, key: str, ttl: int) -> None:
        await self.r.set(key, "1", ex=ttl)

    async def has_flag(self, key: str) -> bool:
        return bool(await self.r.exists(key))

    @asynccontextmanager
    async def slot(self, name: str, slots: int, min_gap_s: float) -> AsyncIterator[None]:
        token = uuid.uuid4().hex
        held: str | None = None
        deadline = time.time() + 120
        while held is None:  # take one of N slot locks (auto-expire if a worker dies)
            for i in range(slots):
                key = f"slot:{name}:{i}"
                if await self.r.set(key, token, nx=True, px=60_000):
                    held = key
                    break
            if held is None:
                if time.time() > deadline:
                    raise TimeoutError(f"no free {name} slot after 120 s")
                await asyncio.sleep(0.3 + random.random() * 0.4)
        try:
            gap_key = f"gap:{name}"
            while not await self.r.set(gap_key, token, nx=True, px=int(min_gap_s * 1000)):
                await asyncio.sleep(0.25 + random.random() * 0.25)
            yield
        finally:
            if await self.r.get(held) in (token, token.encode()):
                await self.r.delete(held)

    async def rate(self, name: str, limit: int, window_s: float = 60.0) -> float:
        """Waits until one more call fits in the window (global across workers); returns seconds waited."""
        waited = 0.0
        window_ms = int(window_s * 1000)
        while True:
            now_ms = int(time.time() * 1000)
            wait_ms = await self.r.eval(_RATE_LUA, 1, f"rate:{name}", now_ms, window_ms, limit,
                                        f"{now_ms}-{uuid.uuid4().hex[:8]}")
            if int(wait_ms) == 0:
                return waited
            pause = int(wait_ms) / 1000 + random.random() * 0.3
            await asyncio.sleep(pause)
            waited += pause


async def make_cache(redis_url: str | None = None) -> Cache:
    url = redis_url if redis_url is not None else os.environ.get("REDIS_URL", "")
    if not url:
        return MemoryCache()
    try:
        import redis.asyncio as redis

        client = redis.from_url(url, socket_connect_timeout=2, socket_timeout=5)
        await client.ping()
        return RedisCache(client)
    except Exception as e:  # Redis down: keep working with an in-process cache
        log.warning("Redis unavailable (%s); using in-memory cache", e)
        return MemoryCache()
