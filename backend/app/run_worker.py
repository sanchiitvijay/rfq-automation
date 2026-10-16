"""Supervised worker:  python -m backend.app.run_worker

arq exits when it loses its Redis connection. This wrapper restarts it with a growing back-off so a
Redis restart never leaves jobs unprocessed (the recovery sweep then picks up anything that waited).
"""
from __future__ import annotations

import logging
import time

from arq import run_worker

from backend.app.worker import WorkerSettings

log = logging.getLogger("rfq.worker.supervisor")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines contain full URLs (API keys)
    delay = 2.0
    while True:
        started = time.monotonic()
        try:
            run_worker(WorkerSettings)  # blocks until the worker stops
            log.info("worker stopped")
            return
        except KeyboardInterrupt:
            return
        except Exception as e:  # Redis gone, network blip…
            log.error("worker crashed (%s: %s); restarting in %.0f s", type(e).__name__, e, delay)
        if time.monotonic() - started > 60:
            delay = 2.0  # it ran fine for a while: start over with a short delay
        time.sleep(delay)
        delay = min(delay * 2, 30.0)


if __name__ == "__main__":
    main()
