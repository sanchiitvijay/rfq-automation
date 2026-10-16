"""Creating jobs, queueing them, and turning them into API responses."""
from __future__ import annotations

import base64
import binascii
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Job
from backend.app.settings import get_settings
from rfq.config import STATUS_NOT_FOUND
from rfq.parse_email import EmailTooLarge, parse_eml

ACTIVE = ("queued", "running")


class BadInput(ValueError):
    pass


def job_dir(job_id: uuid.UUID | str) -> Path:
    return get_settings().storage_dir / str(job_id)


def xlsx_path(job_id: uuid.UUID | str, version: int) -> Path:
    return job_dir(job_id) / f"RFQ_v{version}.xlsx"


def decode_eml(raw_b64: str) -> bytes:
    try:
        raw = base64.b64decode(raw_b64, validate=False)
    except (binascii.Error, ValueError) as e:
        raise BadInput("raw_eml_b64 is not valid base64") from e
    if len(raw) > get_settings().max_upload_bytes:
        raise BadInput("email is larger than 15 MB")
    if b":" not in raw[:2000]:
        raise BadInput("raw_eml_b64 does not look like an email (no headers)")
    return raw


async def find_by_gmail_id(session: AsyncSession, gmail_msg_id: str) -> Job | None:
    return (await session.execute(select(Job).where(Job.gmail_msg_id == gmail_msg_id))).scalar_one_or_none()


def new_job(source: str, *, raw: bytes | None = None, subject: str = "", sender: str = "", body: str = "",
            gmail_msg_id: str | None = None, warnings: list[str] | None = None) -> Job:
    job = Job(id=uuid.uuid4(), source=source, gmail_msg_id=gmail_msg_id or None, status="queued",
              phase="Queued", progress=0, version=0, warnings=list(warnings or []), attachments=[])
    if raw is not None:
        try:
            parsed = parse_eml(raw)
        except EmailTooLarge as e:
            raise BadInput(str(e)) from e
        job.raw_eml = raw
        job.subject, job.sender, job.email_date = parsed.subject, parsed.sender, parsed.date
        job.message_id = parsed.message_id
        job.body_text = parsed.body
        job.attachments = [name for name, _ in parsed.attachments]
        job.warnings = job.warnings + parsed.warnings
    else:
        if not body.strip():
            raise BadInput("the email body is empty")
        job.subject, job.sender, job.body_text = subject, sender, body
    if not job.subject:
        job.subject = subject or "(no subject)"
    if not job.sender:
        job.sender = sender
    return job


def _counts(job: Job) -> dict[str, Any]:
    sheet = job.sheet or {}
    rows = sheet.get("rows", [])
    not_found = sum(1 for r in rows if r.get("lookup_status") == STATUS_NOT_FOUND)
    report = job.report or {}
    flags = report.get("flags", [])
    return {
        "requested": len(rows),
        "found": len(rows) - not_found,
        "not_found": not_found,
        "fill_rate": report.get("fill_overall"),
        "suspicious": sum(1 for f in flags if f.get("type") == "suspicious"),
        "missing": sum(1 for f in flags if f.get("type") == "missing"),
    }


def summary(job: Job) -> dict[str, Any]:
    return {
        "id": str(job.id), "source": job.source, "subject": job.subject, "sender": job.sender,
        "status": job.status, "phase": job.phase, "progress": job.progress, "eta_seconds": job.eta_seconds,
        "error": job.error, "version": job.version, "created_at": job.created_at,
        "started_at": job.started_at, "finished_at": job.finished_at, **_counts(job),
    }


def detail(job: Job) -> dict[str, Any]:
    sheet = job.sheet or {}
    return {
        **summary(job),
        "email": {"subject": job.subject, "sender": job.sender, "date": job.email_date,
                  "body": job.body_text, "attachments": job.attachments or [],
                  "has_raw": job.raw_eml is not None},
        "items": [{"position": i.position, "raw_token": i.raw_token, "product_id": i.product_id, "kind": i.kind,
                   "qty": i.qty, "context": i.context, "origin": i.origin, "occurrences": i.occurrences,
                   "lookup_status": i.lookup_status, "lookup_source": i.lookup_source, "notes": i.notes}
                  for i in job.items],
        "warnings": (job.warnings or []) + [w for w in sheet.get("warnings", []) if w not in (job.warnings or [])],
        "notes": sheet.get("notes", []),
        "report": job.report,
        "events": [{"ts": e.ts, "phase": e.phase, "message": e.message} for e in job.events],
        "edits": [{"ts": e.ts, "version": e.version, "product_id": e.product_id, "column": e.column,
                   "old": e.old, "new": e.new, "note": e.note, "user": e.user} for e in job.edits[-200:]],
        "sends": [{"id": s.id, "version": s.version, "to": s.to, "cc": s.cc, "status": s.status, "error": s.error,
                   "attempts": s.attempts, "created_at": s.created_at, "sent_at": s.sent_at, "user": s.user}
                  for s in job.sends],
    }


def delete_files(job_id: uuid.UUID) -> None:
    shutil.rmtree(job_dir(job_id), ignore_errors=True)
