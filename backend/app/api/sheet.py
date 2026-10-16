"""Human-in-the-loop review: read the sheet, edit cells, re-run checks, mark as reviewed."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app import events
from backend.app.db import get_session
from backend.app.deps import cache, load_job
from backend.app.models import Job, JobEvent
from backend.app.schemas import SheetPatch
from backend.app.security import current_user
from backend.app.services import jobs as svc
from rfq.excel.importer import MAX_UPLOAD_BYTES, preview
from rfq.excel.reader import read as read_workbook
from rfq.models import Sheet
from backend.app.services.sheet import (
    Conflict, Invalid, RecheckBusy, apply_patch, incomplete, recheck, sheet_payload,
)

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["review"])


def _ready(job: Job) -> None:
    if job.sheet is None:
        raise HTTPException(409, f"the RFQ is not ready yet (status {job.status})")


@router.get("/sheet")
async def get_sheet(job: Job = Depends(load_job)) -> dict:
    _ready(job)
    return {**sheet_payload(job), "incomplete": incomplete(job)}


@router.patch("/sheet")
async def patch_sheet(patch: SheetPatch, job: Job = Depends(load_job), session: AsyncSession = Depends(get_session),
                      user: str = Depends(current_user), c=Depends(cache)):
    _ready(job)
    try:
        job = await apply_patch(session, job, patch, user, c)
    except Conflict as e:
        return JSONResponse(status_code=409, content={"detail": str(e), "current_version": e.current_version})
    except Invalid as e:
        return JSONResponse(status_code=422, content={"detail": str(e), "errors": e.errors})
    await events.publish(str(job.id), {"type": "sheet", "version": job.version, "job": svc.summary(job)})
    return {**sheet_payload(job), "incomplete": incomplete(job)}


@router.post("/sheet/import")
async def import_sheet(file: UploadFile = File(...), job: Job = Depends(load_job)) -> dict:
    """Preview what an edited, re-uploaded RFQ workbook would change. Writes nothing: the web app shows the
    preview and applies the chosen changes through PATCH /sheet (validated and versioned)."""
    _ready(job)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    current = Sheet.from_dict(job.sheet or {})
    base = None
    meta_version = _meta_version(data, file.filename or "")
    if meta_version and meta_version != job.version:
        path = svc.xlsx_path(job.id, meta_version)
        if path.exists():
            base = await asyncio.to_thread(read_workbook, path)
    result = await asyncio.to_thread(preview, data, file.filename or "upload.xlsx", str(job.id), current,
                                     job.version, base)
    if meta_version and meta_version != job.version and base is None:
        result.warnings.append(f"Version {meta_version} of this RFQ is no longer stored, so the file is compared "
                               "with the current version only.")
    return result.to_dict()


def _meta_version(data: bytes, filename: str) -> int | None:
    """The version stamp in an uploaded workbook (.xlsx or .xls); CSV files never have one."""
    from rfq.excel.importer import ImportPreview, load_table

    loaded = load_table(data, filename, ImportPreview(ok=False, filename=filename))
    value = loaded[0].get("version", "") if loaded else ""
    return int(value) if value.isdigit() else None


@router.post("/recheck")
async def recheck_sheet(job: Job = Depends(load_job), session: AsyncSession = Depends(get_session), c=Depends(cache)):
    _ready(job)
    if job.status in ("running", "sending"):
        raise HTTPException(409, f"wait until the job is not {job.status}")
    try:
        job = await recheck(session, job, c)
    except RecheckBusy as e:
        raise HTTPException(409, str(e)) from e
    await events.publish(str(job.id), {"type": "sheet", "version": job.version, "job": svc.summary(job)})
    return {**sheet_payload(job), "incomplete": incomplete(job)}


@router.post("/review")
async def mark_reviewed(done: bool = True, version: int | None = None, job: Job = Depends(load_job),
                        session: AsyncSession = Depends(get_session), user: str = Depends(current_user)):
    _ready(job)
    if job.status not in ("needs_review", "ready"):
        raise HTTPException(409, f"cannot change review state while {job.status}")
    if version is not None and version != job.version:  # reviewed what they saw, not a newer version
        raise HTTPException(409, f"the RFQ changed (now version {job.version}); look at the changes, then mark it reviewed")
    job.status = "ready" if done else "needs_review"
    session.add(JobEvent(job_id=job.id, phase="Reviewed" if done else "Review reopened",
                         message=f"by {user} (version {job.version})"))
    await session.commit()
    await events.publish(str(job.id), {"type": "status", "job": svc.summary(job)})
    return svc.summary(job)
