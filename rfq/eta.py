"""Phase reporting and an approximate time-left estimate.

Each kind of work (a live lookup, a PDF, an LLM batch…) has an average duration kept as a moving
average in the cache, so estimates improve as jobs run. Time left = Σ remaining units × average.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from rfq.lookup.cache import Cache

ProgressFn = Callable[[dict], Awaitable[None]]

DEFAULT_SECONDS = {
    "parse": 0.2, "serp": 1.5, "live": 6.0, "catalog": 0.01, "pdf": 2.0, "fill": 0.3,
    "quality": 0.2, "llm": 8.0, "write": 0.5,
}
EMA_ALPHA = 0.3


@dataclass
class _Stage:
    planned: int = 0
    done: int = 0


class Progress:
    def __init__(self, emit: ProgressFn | None = None, cache: Cache | None = None) -> None:
        self.emit = emit
        self.cache = cache
        self.avg = dict(DEFAULT_SECONDS)
        self.stages: dict[str, _Stage] = {k: _Stage() for k in DEFAULT_SECONDS}
        self.phase = "Queued"
        self._started: dict[str, float] = {}
        self._shown = 0  # last percentage reported
        self._floor: dict[str, float] = {}  # e.g. the rate limit: a page load can never be faster than 60/limit s

    async def load(self) -> None:
        if not self.cache:
            return
        for kind in self.avg:
            try:
                value = await self.cache.get_json(f"eta:{kind}")
            except Exception:
                value = None
            if isinstance(value, (int, float)) and value > 0:
                self.avg[kind] = float(value)

    def plan(self, kind: str, units: int) -> None:
        self.stages[kind].planned = max(units, 0)

    def floor(self, kind: str, seconds: float) -> None:
        self._floor[kind] = seconds

    def _unit(self, kind: str) -> float:
        return max(self.avg[kind], self._floor.get(kind, 0.0))

    def _remaining_s(self) -> float:
        return sum(max(s.planned - s.done, 0) * self._unit(k) for k, s in self.stages.items())

    def _percent(self) -> int:
        total = sum(s.planned * self._unit(k) for k, s in self.stages.items())
        done = sum(min(s.done, s.planned) * self._unit(k) for k, s in self.stages.items())
        return int(round(100 * done / total)) if total else 0

    async def start(self, kind: str, phase: str) -> None:
        self.phase = phase
        self._started[kind] = time.monotonic()
        await self._emit(phase)

    async def step(self, kind: str, message: str = "", units: int = 1) -> None:
        self.stages[kind].done += units
        await self._emit(message or self.phase)

    async def finish(self, kind: str) -> None:
        stage = self.stages[kind]
        stage.done = max(stage.done, stage.planned)
        began = self._started.pop(kind, None)
        if began is not None and stage.planned and kind != "catalog":  # catalog/cache time is negligible
            per_unit = (time.monotonic() - began) / stage.planned
            self.avg[kind] = EMA_ALPHA * per_unit + (1 - EMA_ALPHA) * self.avg[kind]
            if self.cache:
                try:
                    await self.cache.set_json(f"eta:{kind}", self.avg[kind], 30 * 24 * 3600)
                except Exception:
                    pass

    async def done(self, message: str = "Done") -> None:
        for stage in self.stages.values():
            stage.done = stage.planned
        self.phase = "Done"
        await self._emit(message, final=True)

    async def _emit(self, message: str, final: bool = False) -> None:
        if not self.emit:
            return
        # never move the bar backwards when the plan is refined (e.g. once the IDs are known)
        self._shown = 100 if final else max(self._shown, min(self._percent(), 99))
        await self.emit({
            "phase": self.phase,
            "message": message,
            "progress": self._shown,
            "eta_seconds": 0 if final else int(round(self._remaining_s())),
        })
