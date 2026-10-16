"""arq worker: runs RFQ jobs and sends reviewed RFQs. Start with:  arq backend.app.worker.WorkerSettings

Each worker process runs up to WORKER_MAX_JOBS jobs at the same time, and more processes can be
started for more throughput. Jobs never wait on each other; only ferguson.com page loads share a
global, Redis-coordinated rate limit.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from arq import Retry
from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import selectinload

from backend.app import events
from backend.app.db import create_tables, dispose, sessions
from backend.app.models import Job, JobEvent, JobItem, JobSend
from backend.app.services.jobs import job_dir, summary, xlsx_path
from backend.app.services.mail import PermanentSendError, build_message, smtp_send
from backend.app.services.sheet import options
from backend.app.settings import get_settings
from rfq.lookup.cache import make_cache
from rfq.models import Sheet
from rfq.pipeline import run

log = logging.getLogger("rfq.worker")
RFQ_MAX_TRIES = 2
SEND_MAX_TRIES = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _set(job_id: uuid.UUID, **values: Any) -> None:
    async with sessions()() as s:
        await s.execute(update(Job).where(Job.id == job_id).values(**values))
        await s.commit()


async def _event(job_id: uuid.UUID, phase: str, message: str = "") -> None:
    async with sessions()() as s:
        s.add(JobEvent(job_id=job_id, phase=phase, message=message))
        await s.commit()


async def _publish_job(job_id: uuid.UUID, type_: str = "status") -> None:
    async with sessions()() as s:
        job = await s.get(Job, job_id)
        if job:
            await events.publish(str(job_id), {"type": type_, "job": summary(job)})


def _progress_writer(job_id: uuid.UUID):
    """Throttled to ~2 updates/s per job; the latest update of a burst is always delivered (trailing flush)."""
    state: dict[str, Any] = {"t": 0.0, "phase": None, "pending": None, "task": None}
    window = 0.5

    async def flush_later() -> None:
        await asyncio.sleep(window)
        state["task"] = None
        if state["pending"] is not None:
            event, state["pending"] = state["pending"], None
            await write(event)

    async def write(event: dict) -> None:
        changed = event["phase"] != state["phase"]
        now = time.monotonic()
        if not changed and now - state["t"] < window and event["progress"] < 100:
            state["pending"] = event
            if state["task"] is None:
                state["task"] = asyncio.create_task(flush_later())
            return
        if event["progress"] >= 100 and state["task"] is not None:
            state["task"].cancel()  # the final update must never be overwritten by an older one
            state["task"] = None
        state.update(t=now, phase=event["phase"], pending=None)
        async with sessions()() as s:
            await s.execute(update(Job).where(Job.id == job_id).values(
                phase=event["message"], progress=event["progress"], eta_seconds=event["eta_seconds"]))
            if changed:
                s.add(JobEvent(job_id=job_id, phase=event["phase"], message=event["message"]))
            await s.commit()
        await events.publish(str(job_id), {"type": "progress", "status": "running", **event})

    return write


async def run_rfq_job(ctx: dict, job_id: str) -> str:
    jid = uuid.UUID(job_id)
    stale = _now() - timedelta(seconds=get_settings().job_timeout_s + 60)
    async with sessions()() as s:
        # claim atomically: a job is never run twice, even if it was queued twice (recovery, retries)
        claimed = await s.execute(
            update(Job).where(Job.id == jid, or_(Job.status == "queued",
                                                 and_(Job.status == "running", Job.updated_at < stale)))
            .values(status="running", started_at=_now(), error=None, phase="Starting", progress=0)
            .returning(Job.raw_eml, Job.body_text, Job.subject, Job.sender))
        row = claimed.first()
        await s.commit()
    if row is None:
        return "skipped (already taken, finished or deleted)"
    raw, body, subject, sender = row
    await _publish_job(jid)

    try:
        result = await run(job_dir(jid), options(), raw_eml=raw, text=None if raw else body, subject=subject,
                           sender=sender, progress_cb=_progress_writer(jid), cache=ctx["cache"],
                           xlsx_name=xlsx_path(jid, 1).name, meta={"job_id": str(jid), "version": "1"})
    except Exception as e:
        reason = f"{type(e).__name__}: {str(e)[:400]}"
        log.exception("job %s failed", job_id)
        if ctx.get("job_try", 1) < RFQ_MAX_TRIES:
            await _set(jid, phase=f"Retrying after an error ({type(e).__name__})", status="queued")
            await _event(jid, "Retrying", reason)
            await _publish_job(jid)
            raise Retry(defer=5) from e
        await _set(jid, status="failed", error=reason, phase="Failed", finished_at=_now(), eta_seconds=None)
        await _event(jid, "Failed", reason)
        await _publish_job(jid)
        return "failed"

    async with sessions()() as s:
        job = await s.get(Job, jid, options=[selectinload(Job.items)])
        if job is None:  # deleted while running
            return "deleted while running"
        job.items.clear()
        notes = {}
        for n in result.sheet.notes:
            notes.setdefault(n.product_id, []).append(n.note)
        rows = {r.product_id: r for r in result.sheet.rows}
        for item in result.items:
            row = rows.get(item.product_id)
            job.items.append(JobItem(position=item.position, raw_token=item.raw_token, product_id=item.product_id,
                                     kind=item.kind, qty=item.qty, context=item.context, origin=item.origin,
                                     occurrences=item.occurrences,
                                     lookup_status=row.lookup_status if row else "",
                                     lookup_source=row.lookup_source if row else "none",
                                     notes=" ".join(notes.get(item.product_id, []))))
        job.sheet, job.report = result.sheet.to_dict(), result.report.to_dict()
        job.version, job.status, job.finished_at = 1, "needs_review", _now()
        job.phase, job.progress, job.eta_seconds = "Done: ready for review", 100, 0
        await s.commit()
    await _publish_job(jid, "done")
    return "done"


async def send_rfq_email(ctx: dict, send_id: int) -> str:
    settings = get_settings()
    async with sessions()() as s:
        send = await s.get(JobSend, send_id)
        if send is None:
            return "send no longer exists"
        if send.status in ("sent", "failed"):
            return f"already {send.status}"  # idempotent: a retry after success never sends twice
        job = await s.get(Job, send.job_id)
        if job is None:
            return "job no longer exists"
        send.status, send.attempts = "sending", send.attempts + 1
        await s.commit()
        sheet = Sheet.from_dict(job.sheet or {})
        path = xlsx_path(job.id, send.version)
        msg = build_message(settings, sheet, path, to=send.to, cc=[c for c in send.cc.split(",") if c],
                            subject=send.subject, body=send.body, in_reply_to=job.message_id, version=send.version)
        attempts, job_id = send.attempts, job.id

    try:
        message_id = await asyncio.to_thread(smtp_send, settings, msg)
    except Exception as e:
        permanent = isinstance(e, PermanentSendError) or attempts >= SEND_MAX_TRIES
        reason = f"{type(e).__name__}: {str(e)[:300]}"
        async with sessions()() as s:
            send = await s.get(JobSend, send_id)
            job = await s.get(Job, job_id)
            if send:
                send.status, send.error = ("failed" if permanent else "queued"), reason
            if job and permanent:
                job.status, job.error = "needs_review", f"Sending failed: {reason}"
            s.add(JobEvent(job_id=job_id, phase="Send failed" if permanent else "Send retry", message=reason))
            await s.commit()
        await _publish_job(job_id)
        if not permanent:
            raise Retry(defer=10 * attempts) from e
        return "failed"

    async with sessions()() as s:
        send = await s.get(JobSend, send_id)
        job = await s.get(Job, job_id)
        if send:
            send.status, send.message_id, send.sent_at, send.error = "sent", message_id, _now(), None
        if job:
            job.status, job.error, job.phase = "sent", None, f"Sent to {send.to if send else ''}"
        s.add(JobEvent(job_id=job_id, phase="Sent", message=f"to {send.to if send else '?'} (v{send.version if send else '?'})"))
        await s.commit()
    await _publish_job(job_id)
    return "sent"


async def recover_stuck_jobs(ctx: dict) -> str:
    """Re-queue work that was lost: jobs saved while Redis was down, or left running by a dead worker."""
    settings = get_settings()
    now = _now()
    requeued = 0
    async with sessions()() as s:
        waiting = (await s.execute(select(Job.id).where(Job.status == "queued",
                                                        Job.updated_at < now - timedelta(seconds=60)))).scalars().all()
        dead = (await s.execute(select(Job.id).where(
            Job.status == "running", Job.updated_at < now - timedelta(seconds=settings.job_timeout_s + 60)))).scalars().all()
        sends = (await s.execute(select(JobSend.id).where(JobSend.status == "queued",
                                                          JobSend.created_at < now - timedelta(seconds=120)))).scalars().all()
    stamp = int(now.timestamp())
    for jid in [*waiting, *dead]:
        await ctx["redis"].enqueue_job("run_rfq_job", str(jid), _job_id=f"rfq:{jid}:recover:{stamp}")
        requeued += 1
    for sid in sends:  # only "queued" sends: a stuck "sending" may already have gone out, never resend it blindly
        await ctx["redis"].enqueue_job("send_rfq_email", sid, _job_id=f"send:{sid}:recover:{stamp}")
        requeued += 1
    if requeued:
        log.info("recovery: re-queued %s jobs and %s sends", len(waiting) + len(dead), len(sends))
    return f"requeued {requeued}"


async def startup(ctx: dict) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines contain full URLs (API keys)
    await create_tables()
    ctx["cache"] = await make_cache(get_settings().redis_url)


async def shutdown(ctx: dict) -> None:
    await dispose()
    await events.close()


class WorkerSettings:
    functions = [
        func(run_rfq_job, max_tries=RFQ_MAX_TRIES, timeout=get_settings().job_timeout_s),
        func(send_rfq_email, max_tries=SEND_MAX_TRIES, timeout=120),
    ]
    cron_jobs = [cron(recover_stuck_jobs, second={0}, run_at_startup=True, unique=True)]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    redis_settings.conn_retries = 30  # wait for Redis at start-up instead of exiting at once
    redis_settings.conn_retry_delay = 2
    max_jobs = get_settings().worker_max_jobs
    on_startup = startup
    on_shutdown = shutdown
    keep_result = 3600
    allow_abort_jobs = True
