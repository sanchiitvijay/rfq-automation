"""Send the reviewed RFQ to the point of contact (human click only, validated, idempotent)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app import events
from backend.app.db import get_session
from backend.app.deps import load_job, queue
from backend.app.models import Job, JobEvent, JobSend
from backend.app.schemas import SendRequest
from backend.app.security import current_user
from backend.app.services import jobs as svc
from backend.app.services.mail import RecipientRejected, check_recipient
from backend.app.services.sheet import incomplete
from backend.app.settings import get_settings

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["send"])


def _send_out(s: JobSend) -> dict:
    return {"id": s.id, "version": s.version, "to": s.to, "cc": s.cc, "status": s.status, "error": s.error,
            "attempts": s.attempts, "created_at": s.created_at, "sent_at": s.sent_at}


@router.post("/send", status_code=202)
async def send_rfq(body: SendRequest, job: Job = Depends(load_job), session: AsyncSession = Depends(get_session),
                   pool=Depends(queue), user: str = Depends(current_user)) -> dict:
    settings = get_settings()
    same_key = (await session.execute(select(JobSend).where(JobSend.idempotency_key == body.idempotency_key))
                ).scalar_one_or_none()
    if same_key:  # double click or network retry: return the existing send, never a second email
        if same_key.job_id != job.id:
            raise HTTPException(409, "idempotency key already used for another job")
        return _send_out(same_key)
    if job.sheet is None or job.status not in ("needs_review", "ready", "sent"):
        raise HTTPException(409, f"the RFQ cannot be sent while the job is {job.status}")
    if job.status == "sent" and not body.resend:
        raise HTTPException(409, "this version was already sent; tick 'send again' to send it once more")
    try:
        to = check_recipient(body.to, settings.allowed_domains)
        cc = [check_recipient(c, settings.allowed_domains) for c in body.cc]
    except RecipientRejected as e:
        raise HTTPException(422, f"recipient not accepted: {e}") from e
    gaps = incomplete(job)
    if not gaps["complete"] and not body.confirm_incomplete:
        raise HTTPException(409, {"message": "the RFQ still has missing fields or products that were not found; "
                                             "confirm to send anyway", "incomplete": gaps})
    if not settings.bot_email:
        raise HTTPException(503, "sending is not configured: set BOT_EMAIL and BOT_PASSWORD in .env")
    if not svc.xlsx_path(job.id, job.version).exists():
        raise HTTPException(409, "the RFQ file for this version is missing; edit or re-check to regenerate it")

    send = JobSend(job_id=job.id, version=job.version, idempotency_key=body.idempotency_key, to=to, cc=",".join(cc),
                   subject=body.subject.replace("\n", " ").strip(), body=body.body, user=user, status="queued")
    session.add(send)
    session.add(JobEvent(job_id=job.id, phase="Send requested", message=f"by {user} to {to} (v{job.version})"))
    try:
        await session.flush()  # the unique idempotency key is checked here
        # only one request may move the job to "sending" (two people clicking Send at the same moment)
        moved = await session.execute(
            update(Job).where(Job.id == job.id, Job.version == job.version,
                              Job.status.in_(("needs_review", "ready", "sent")))
            .values(status="sending").execution_options(synchronize_session=False))
        if moved.rowcount != 1:
            await session.rollback()
            raise HTTPException(409, "this RFQ is already being sent or was changed; reload and try again")
        await session.commit()
    except IntegrityError:  # the same click arrived twice at the same moment: the other request won
        await session.rollback()
        winner = (await session.execute(select(JobSend).where(JobSend.idempotency_key == body.idempotency_key))
                  ).scalar_one()
        return _send_out(winner)
    await session.refresh(send)
    await session.refresh(job)
    await pool.enqueue_job("send_rfq_email", send.id, _job_id=f"send:{send.id}")
    await events.publish(str(job.id), {"type": "status", "job": svc.summary(job)})
    return _send_out(send)
