"""Creating, listing and downloading jobs."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app import events
from backend.app.db import get_session
from backend.app.deps import load_job, queue, queue_or_none
from backend.app.models import Job
from backend.app.schemas import CreateJob
from backend.app.services import jobs as svc
from backend.app.settings import get_settings
from rfq.models import QualityReport, Sheet
from rfq.reply import build_reply

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


async def _enqueue(pool, job: Job) -> bool:
    """False when the queue is unreachable: the job stays saved as queued and the worker's
    recovery sweep starts it as soon as Redis is back."""
    try:
        await pool.enqueue_job("run_rfq_job", str(job.id), _job_id=f"rfq:{job.id}")  # arq de-duplicates by id
        return True
    except Exception as e:
        log.warning("could not queue job %s: %s", job.id, e)
        return False


async def _create(session: AsyncSession, pool, job: Job) -> dict:
    session.add(job)
    await session.commit()
    await session.refresh(job)
    queued = await _enqueue(pool, job)
    await events.publish(str(job.id), {"type": "created", "job": svc.summary(job)})
    out = {"job_id": str(job.id), "url": f"{get_settings().frontend_url}/jobs/{job.id}", "created": True,
           "queued": queued}
    if not queued:
        out["message"] = "Saved. The job queue is not reachable right now; it starts automatically when it is back."
    return out


@router.post("", status_code=201)
async def create_job(body: CreateJob, session: AsyncSession = Depends(get_session), pool=Depends(queue_or_none)) -> dict:
    if body.gmail_msg_id and not body.force:
        existing = await svc.find_by_gmail_id(session, body.gmail_msg_id)
        if existing:  # double click / re-open: no duplicate job
            return {"job_id": str(existing.id), "url": f"{get_settings().frontend_url}/jobs/{existing.id}",
                    "created": False}
    if body.gmail_msg_id and body.force:
        existing = await svc.find_by_gmail_id(session, body.gmail_msg_id)
        if existing:
            existing.gmail_msg_id = None  # keep the old job, let the new one own the id
            await session.flush()
    try:
        raw = svc.decode_eml(body.raw_eml_b64) if body.raw_eml_b64 else None
        job = svc.new_job(body.source, raw=raw, subject=body.subject, sender=body.sender, body=body.body_text,
                          gmail_msg_id=body.gmail_msg_id, warnings=body.extract_warnings)
    except svc.BadInput as e:
        raise HTTPException(422, str(e)) from e
    return await _create(session, pool, job)


@router.post("/upload", status_code=201)
async def upload_eml(file: UploadFile = File(...), session: AsyncSession = Depends(get_session),
                     pool=Depends(queue_or_none)) -> dict:
    limit = get_settings().max_upload_bytes
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(413, "email is larger than 15 MB")
    if not (file.filename or "").lower().endswith(".eml"):
        raise HTTPException(422, "please upload a .eml file (in Gmail: ⋮ → Download message)")
    try:
        job = svc.new_job("upload", raw=raw)
    except svc.BadInput as e:
        raise HTTPException(422, str(e)) from e
    return await _create(session, pool, job)


@router.get("")
async def list_jobs(limit: int = 50, status: str | None = None, session: AsyncSession = Depends(get_session)) -> list:
    query = select(Job).order_by(Job.created_at.desc()).limit(max(1, min(limit, 200)))
    if status:
        query = query.where(Job.status == status)
    return [svc.summary(j) for j in (await session.execute(query)).scalars()]


@router.get("/{job_id}")
async def get_job(job: Job = Depends(load_job)) -> dict:
    return svc.detail(job)


@router.post("/{job_id}/retry")
async def retry_job(job: Job = Depends(load_job), session: AsyncSession = Depends(get_session),
                    pool=Depends(queue)) -> dict:
    if job.status != "failed":
        raise HTTPException(409, f"only failed jobs can be retried (status is {job.status})")
    job.status, job.error, job.phase, job.progress = "queued", None, "Queued (retry)", 0
    await session.commit()
    await pool.enqueue_job("run_rfq_job", str(job.id), _job_id=f"rfq:{job.id}:retry:{uuid.uuid4().hex[:8]}")
    return svc.summary(job)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job: Job = Depends(load_job), session: AsyncSession = Depends(get_session)) -> Response:
    if job.status in ("running", "sending"):
        raise HTTPException(409, "wait until the job has finished before deleting it")
    await session.delete(job)
    await session.commit()
    svc.delete_files(job.id)
    return Response(status_code=204)


@router.get("/{job_id}/rfq.xlsx")
async def download_xlsx(version: int | None = None, job: Job = Depends(load_job)) -> FileResponse:
    v = version or job.version
    path = svc.xlsx_path(job.id, v)
    if v < 1 or not path.exists():
        raise HTTPException(404, "no RFQ file for this version yet")
    return FileResponse(path, filename="RFQ.xlsx" if v == 1 else f"RFQ_v{v}.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/{job_id}/reply.eml")
async def download_reply(job: Job = Depends(load_job)) -> Response:
    path = svc.xlsx_path(job.id, job.version)
    if not job.sheet or not path.exists():
        raise HTTPException(404, "no reply yet")
    report = QualityReport.from_dict(job.report) if job.report else None
    msg = build_reply(Sheet.from_dict(job.sheet), report, path, subject=job.subject, to=job.sender)
    return Response(bytes(msg), media_type="message/rfc822",
                    headers={"Content-Disposition": 'attachment; filename="reply.eml"'})
