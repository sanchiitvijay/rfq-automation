"""Creating, listing and downloading jobs."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app import events
from backend.app.db import get_session
from backend.app.deps import load_job, queue, queue_or_none
from backend.app.models import Job
from backend.app.schemas import CreateJob
from backend.app.services import jobs as svc
from backend.app.services import search
from rfq.config import RunOptions
from rfq.excel import exports
from rfq.excel.reader import read as read_workbook
from rfq.excel.writer import render_summary_bytes
from rfq.quality.agent import run_quality
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
async def list_jobs(
    q: str | None = Query(None, description="free text: subject, sender, email body or product ID"),
    subject: str | None = None, sender: str | None = None, product: str | None = None,
    status: list[str] | None = Query(None), source: list[str] | None = Query(None),
    created_from: datetime | None = None, created_to: datetime | None = None,
    sort: str | None = None, page: int = Query(1, ge=1, le=100_000),
    page_size: int = Query(search.DEFAULT_PAGE_SIZE, ge=1, le=max(search.PAGE_SIZES)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        filters = search.Filters.parse(q=q, subject=subject, sender=sender, product=product, status=status,
                                       source=source, created_from=created_from, created_to=created_to, sort=sort)
    except search.SearchError as e:
        raise HTTPException(422, str(e)) from e
    jobs, total, page = await search.search(session, filters, page, page_size)
    return {"items": [svc.summary(j) for j in jobs], "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size))}


@router.get("/facets")
async def job_facets(session: AsyncSession = Depends(get_session)) -> dict:
    """Every filter option the jobs list offers, with labels and live counts."""
    return await search.facets(session)


@router.get("/suggest")
async def job_suggest(q: str = Query("", max_length=search.MAX_TEXT), limit: int = Query(search.SUGGEST_LIMIT, ge=1, le=20),
                      session: AsyncSession = Depends(get_session)) -> list:
    return await search.suggest(session, q, limit)


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


async def _export(job: Job, what: str, fmt: str, version: int | None) -> Response:
    if not job.sheet:
        raise HTTPException(404, "the RFQ is not ready yet")
    v = version or job.version
    path = svc.xlsx_path(job.id, v)
    if v < 1 or v > job.version or not path.exists():
        raise HTTPException(404, f"no RFQ file for version {v}")
    if v == job.version:
        sheet = Sheet.from_dict(job.sheet)
        report = QualityReport.from_dict(job.report) if job.report else QualityReport()
    else:  # an older version: rebuild from exactly the file that was downloadable then
        sheet = await asyncio.to_thread(read_workbook, path)
        report = await run_quality(sheet, RunOptions(), llm=False)
    info = {"subject": job.subject, "sender": job.sender}
    rfq_bytes = await asyncio.to_thread(path.read_bytes)
    summary_bytes = await asyncio.to_thread(render_summary_bytes, sheet, report, info)
    try:
        data, f = await asyncio.to_thread(exports.export, what, fmt, rfq_xlsx=rfq_bytes, summary_xlsx=summary_bytes,
                                          sheet=sheet, report=report)
    except exports.ExportError as e:
        raise HTTPException(422, str(e)) from e
    base = "RFQ" if what == "rfq" else "RFQ_summary"
    name = f"{base}{'' if v == 1 else f'_v{v}'}{f.extension}"
    return Response(data, media_type=f.media_type, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/{job_id}/export")
async def export_job(what: str = Query("rfq", pattern="^(rfq|summary)$"), format: str = Query("xlsx", max_length=10),
                     version: int | None = Query(None, ge=1), job: Job = Depends(load_job)) -> Response:
    """Download the RFQ or the Summary as .xlsx, .xls or .csv (see GET /api/exports/formats)."""
    return await _export(job, what, format, version)


@router.get("/{job_id}/rfq.xlsx")
async def download_xlsx(version: int | None = Query(None, ge=1), job: Job = Depends(load_job)) -> Response:
    return await _export(job, "rfq", "xlsx", version)


@router.get("/{job_id}/summary.xlsx")
async def download_summary(job: Job = Depends(load_job)) -> Response:
    """The Summary sheet on its own (fill rates, not-found list, flags) plus the Notes, for the current version."""
    return await _export(job, "summary", "xlsx", None)


@router.get("/{job_id}/reply.eml")
async def download_reply(job: Job = Depends(load_job)) -> Response:
    path = svc.xlsx_path(job.id, job.version)
    if not job.sheet or not path.exists():
        raise HTTPException(404, "no reply yet")
    report = QualityReport.from_dict(job.report) if job.report else None
    msg = build_reply(Sheet.from_dict(job.sheet), report, path, subject=job.subject, to=job.sender)
    return Response(bytes(msg), media_type="message/rfc822",
                    headers={"Content-Disposition": 'attachment; filename="reply.eml"'})
