"""Human-in-the-loop editing: validate, apply with optimistic locking, re-check, regenerate the Excel."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Job, JobEdit
from backend.app.schemas import SheetPatch
from backend.app.services.jobs import xlsx_path
from backend.app.settings import get_settings
from rfq.config import RFQ_COLUMNS, STATUS_FOUND, STATUS_MANUAL, STATUS_NOT_FOUND, RunOptions
from rfq.excel.writer import render
from rfq.lookup.cache import Cache
from rfq.models import Cell, QualityReport, Sheet
from rfq.quality.agent import run_quality
from rfq.validation import EditError, validate


class Conflict(Exception):
    def __init__(self, current_version: int) -> None:
        super().__init__(f"the sheet was changed by someone else (now version {current_version})")
        self.current_version = current_version


class Invalid(Exception):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("some values are not valid")
        self.errors = errors


def options() -> RunOptions:
    s = get_settings()
    return RunOptions(offline=s.rfq_offline, use_llm=s.rfq_use_llm, cdp_url=s.chrome_cdp_url)


def sheet_payload(job: Job) -> dict[str, Any]:
    sheet = job.sheet or {"rows": []}
    return {"version": job.version, "status": job.status, "columns": RFQ_COLUMNS, "rows": sheet.get("rows", []),
            "flags": (job.report or {}).get("flags", []), "report": job.report}


def email_info(job: Job) -> dict[str, str]:
    return {"subject": job.subject, "sender": job.sender}


async def regenerate(job: Job, sheet: Sheet, report: QualityReport) -> None:
    path = xlsx_path(job.id, job.version)
    await asyncio.to_thread(render, sheet, path, report, email_info(job))  # openpyxl is CPU-bound


def _apply(sheet: Sheet, patch: SheetPatch, user: str, version: int) -> list[JobEdit]:
    rows = {r.product_id: r for r in sheet.rows}
    errors: list[dict[str, str]] = []
    for edit in patch.edits:
        if edit.product_id not in rows:
            errors.append({"product_id": edit.product_id, "column": edit.column, "error": "unknown product"})
            continue
        try:
            edit.value = validate(edit.column, edit.value)
        except EditError as e:
            errors.append({"product_id": edit.product_id, "column": edit.column, "error": str(e)})
    for removal in patch.remove_rows:
        if removal.product_id not in rows:
            errors.append({"product_id": removal.product_id, "column": "", "error": "unknown product"})
    if errors:
        raise Invalid(errors)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log: list[JobEdit] = []
    for edit in patch.edits:
        row = rows[edit.product_id]
        old = row.value(edit.column)
        if old == edit.value:
            continue
        note = edit.note.strip()
        if edit.value:
            source = f"{user} on {stamp}" + (f": {note}" if note else " (no note given)")
            row.cells[edit.column] = Cell(edit.value, "manual_edit", "high", source)
        else:
            row.cells.pop(edit.column, None)
        if row.lookup_status == STATUS_NOT_FOUND and row.cells:
            row.lookup_status, row.lookup_source = STATUS_MANUAL, "manual"
            sheet.add_note(row.product_id, f"Filled by hand by {user} (was Not found).")
        elif row.lookup_status == STATUS_MANUAL and not row.cells:
            row.lookup_status, row.lookup_source = STATUS_NOT_FOUND, "none"
        log.append(JobEdit(version=version, product_id=row.product_id, column=edit.column, old=old,
                           new=edit.value, note=note, user=user))
    for removal in patch.remove_rows:
        sheet.rows = [r for r in sheet.rows if r.product_id != removal.product_id]
        sheet.add_note(removal.product_id, f"Removed from the RFQ by {user}: {removal.reason}")
        log.append(JobEdit(version=version, product_id=removal.product_id, column="(row removed)",
                           old="", new="", note=removal.reason, user=user))
    return log


async def apply_patch(session: AsyncSession, job: Job, patch: SheetPatch, user: str, cache: Cache) -> Job:
    if job.status in ("queued", "running", "sending"):
        raise Conflict(job.version)
    if patch.version != job.version:
        raise Conflict(job.version)
    sheet = Sheet.from_dict(job.sheet or {})
    new_version = job.version + 1
    log = _apply(sheet, patch, user, new_version)
    if not log:
        return job
    report = await run_quality(sheet, options(), cache, llm_cache_only=True)

    # optimistic lock: only one writer can move the version forward
    result = await session.execute(
        update(Job).where(Job.id == job.id, Job.version == patch.version)
        .values(version=new_version, sheet=sheet.to_dict(), report=report.to_dict(),
                status="needs_review", error=None, phase=f"Edited by {user} (version {new_version})")
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await session.rollback()
        await session.refresh(job)
        raise Conflict(job.version)
    for entry in log:
        entry.job_id = job.id
        session.add(entry)
    await session.commit()
    await session.refresh(job)
    await regenerate(job, sheet, report)
    return job


async def recheck(session: AsyncSession, job: Job, cache: Cache) -> Job:
    """Full quality pass including the AI check (on demand from the review screen)."""
    sheet = Sheet.from_dict(job.sheet or {})
    report = await run_quality(sheet, options(), cache, llm=True)
    job.report = report.to_dict()
    await session.commit()
    await regenerate(job, sheet, report)
    return job


def incomplete(job: Job) -> dict[str, Any]:
    sheet = Sheet.from_dict(job.sheet or {})
    not_found = [r.product_id for r in sheet.rows if r.lookup_status == STATUS_NOT_FOUND]
    missing = {r.product_id: r.missing_columns() for r in sheet.rows
               if r.lookup_status in (STATUS_FOUND, STATUS_MANUAL) and r.missing_columns()}
    flagged = sum(1 for f in (job.report or {}).get("flags", []) if f.get("type") == "suspicious")
    return {"not_found": not_found, "missing": missing, "suspicious": flagged,
            "complete": not not_found and not missing}
