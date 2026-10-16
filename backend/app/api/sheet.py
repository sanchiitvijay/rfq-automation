"""Human-in-the-loop review: read the sheet, edit cells, re-run checks, mark as reviewed."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app import events
from backend.app.db import get_session
from backend.app.deps import cache, load_job
from backend.app.models import Job
from backend.app.schemas import SheetPatch
from backend.app.security import current_user
from backend.app.services import jobs as svc
from backend.app.services.sheet import Conflict, Invalid, apply_patch, incomplete, recheck, sheet_payload

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


@router.post("/recheck")
async def recheck_sheet(job: Job = Depends(load_job), session: AsyncSession = Depends(get_session), c=Depends(cache)):
    _ready(job)
    if job.status in ("running", "sending"):
        raise HTTPException(409, f"wait until the job is not {job.status}")
    job = await recheck(session, job, c)
    await events.publish(str(job.id), {"type": "sheet", "version": job.version, "job": svc.summary(job)})
    return {**sheet_payload(job), "incomplete": incomplete(job)}


@router.post("/review")
async def mark_reviewed(done: bool = True, job: Job = Depends(load_job), session: AsyncSession = Depends(get_session)):
    _ready(job)
    if job.status not in ("needs_review", "ready"):
        raise HTTPException(409, f"cannot change review state while {job.status}")
    job.status = "ready" if done else "needs_review"
    await session.commit()
    await events.publish(str(job.id), {"type": "status", "job": svc.summary(job)})
    return svc.summary(job)
