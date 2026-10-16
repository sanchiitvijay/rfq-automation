"""FastAPI app.  Run:  uvicorn backend.app.main:app --reload --port 8000"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from backend.app import events
from backend.app.api import jobs, send, sheet, stream
from backend.app.db import create_tables, dispose, sessions
from backend.app.security import require_key
from backend.app.settings import get_settings
from rfq.config import RunOptions
from rfq.lookup.cache import make_cache
from rfq.lookup.serpapi import EXHAUSTED_FLAG
from redis.exceptions import ConnectionError as RedisConnectionError

log = logging.getLogger("rfq.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.api_key == "dev-key-change-me":
        log.warning("API_KEY is the development default; set API_KEY in .env")
    try:
        await create_tables()
    except Exception as e:  # keep serving /api/health so the problem is visible
        log.error("database not reachable at start-up: %s", e)
    try:
        app.state.queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception as e:
        log.error("Redis not reachable at start-up: %s", e)
        app.state.queue = None
    app.state.cache = await make_cache(settings.redis_url)
    yield
    if app.state.queue is not None:
        await app.state.queue.aclose()
    await events.close()
    await dispose()


app = FastAPI(title="Ferguson RFQ Agent", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_origin_regex=r"chrome-extension://[a-p]{32}",
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["X-API-Key", "X-User", "Content-Type"],
)

for router in (jobs.router, sheet.router, send.router, stream.router):
    app.include_router(router, dependencies=[Depends(require_key)])


@app.exception_handler(OperationalError)
@app.exception_handler(DBAPIError)
@app.exception_handler(ConnectionRefusedError)
@app.exception_handler(RedisConnectionError)
async def unavailable(request: Request, exc: Exception) -> JSONResponse:
    log.error("backing service unavailable: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "A backing service (Postgres or Redis) is not available. "
                                                            "Check that both are running."})


@app.get("/api/exports/formats", dependencies=[Depends(require_key)])
async def export_formats() -> dict:
    """Download and upload formats offered by the web app (it builds its menus from this)."""
    from rfq.excel.exports import FORMATS, UPLOAD_EXTENSIONS

    return {
        "download": [{"value": f.value, "label": f.label, "description": f.description, "extension": f.extension}
                     for f in FORMATS.values()],
        "downloads": [{"value": "rfq", "label": "RFQ"}, {"value": "summary", "label": "Summary"}],
        "upload": {"extensions": list(UPLOAD_EXTENSIONS), "accept": ",".join(UPLOAD_EXTENSIONS),
                   "label": "Excel (.xlsx, .xlsm, .xls) or CSV (.csv)"},
    }


@app.post("/api/mail/test", dependencies=[Depends(require_key)])
async def test_mail() -> dict:
    """Logs in to the mail server with BOT_EMAIL / BOT_PASSWORD; never sends a message."""
    import asyncio

    from backend.app.services.mail import PermanentSendError, check_login

    try:
        return {"ok": True, "detail": await asyncio.to_thread(check_login, get_settings())}
    except PermanentSendError as e:
        return {"ok": False, "detail": str(e)}


@app.get("/api/health")
async def health() -> dict:
    out = {"api": "ok", "db": "down", "redis": "down", "queue": "down", "chrome": "down"}
    try:
        async with sessions()() as s:
            await s.execute(text("select 1"))
        out["db"] = "ok"
    except Exception:
        pass
    try:
        await events.client().ping()
        out["redis"] = "ok"
    except Exception:
        pass
    out["queue"] = "ok" if getattr(app.state, "queue", None) is not None else "down"
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(get_settings().chrome_cdp_url.rstrip("/") + "/json/version")
            out["chrome"] = "ok" if r.status_code == 200 else "down"
    except Exception:
        pass
    opts = RunOptions()
    if not opts.serpapi_key:
        out["serpapi"] = "not configured"
    else:
        try:
            exhausted = await events.client().exists(EXHAUSTED_FLAG)
        except Exception:
            exhausted = False
        out["serpapi"] = "quota used up (paused)" if exhausted else "ok"
    out["ferguson_rate_per_minute"] = opts.ferguson_rate_per_minute
    out["mode"] = "offline" if get_settings().rfq_offline else "live"
    out["sending"] = "configured" if get_settings().bot_email else "not configured"
    return out
