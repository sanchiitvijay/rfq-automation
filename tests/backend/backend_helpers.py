"""Fake queue + job runner for backend tests."""
from __future__ import annotations

from backend.app import worker as worker_mod


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple]] = []

    async def enqueue_job(self, name, *args, _job_id=None, **kw):
        self.jobs.append((name, args))

    async def aclose(self):
        pass


async def drain(queue: FakeQueue, ctx: dict) -> None:
    """Run every queued job the way the arq worker would."""
    while queue.jobs:
        name, args = queue.jobs.pop(0)
        await getattr(worker_mod, name)(ctx, *args)
