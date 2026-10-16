"""Searching and filtering jobs in the database (used by the jobs list and the header search).

The server owns every option the UI offers (statuses, sources, sort orders, page sizes, labels), so
the web app builds its filters from /api/jobs/facets instead of hardcoding them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, and_, asc, desc, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Job, JobItem

STATUS_LABELS = {
    "queued": "Queued", "running": "Processing", "needs_review": "Needs review", "ready": "Reviewed",
    "sending": "Sending", "sent": "Sent", "failed": "Failed",
}
SOURCE_LABELS = {"extension": "Gmail extension", "paste": "Pasted", "upload": ".eml upload", "mailbot": "Inbox bot"}
SORTS: dict[str, tuple[str, Any]] = {
    "newest": ("Newest first", desc(Job.created_at)),
    "oldest": ("Oldest first", asc(Job.created_at)),
    "subject": ("Subject A–Z", asc(func.lower(Job.subject))),
    "sender": ("Sender A–Z", asc(func.lower(Job.sender))),
    "updated": ("Recently changed", desc(Job.updated_at)),
}
PAGE_SIZES = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
MAX_TEXT = 200
SUGGEST_LIMIT = 8
# "Received" dropdown: days back from today (0 = today only). Custom dates stay possible.
DATE_PRESETS = (("today", "Today", 0), ("7d", "Last 7 days", 6), ("30d", "Last 30 days", 29), ("90d", "Last 90 days", 89))
FIELD_LABELS = {"q": "Anything", "product": "Product ID", "subject": "Subject", "sender": "Sender"}


class SearchError(ValueError):
    pass


def _like(term: str) -> str:
    """User text as a LIKE pattern: %, _ and \\ in the input are literal characters, not wildcards."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _clean(value: str | None) -> str:
    text = " ".join((value or "").split())
    if len(text) > MAX_TEXT:
        raise SearchError(f"search text is longer than {MAX_TEXT} characters")
    return text


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass
class Filters:
    q: str = ""
    subject: str = ""
    sender: str = ""
    product: str = ""
    statuses: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    created_from: datetime | None = None
    created_to: datetime | None = None
    sort: str = "newest"

    @classmethod
    def parse(cls, *, q: str | None, subject: str | None, sender: str | None, product: str | None,
              status: list[str] | None, source: list[str] | None, created_from: datetime | None,
              created_to: datetime | None, sort: str | None) -> Filters:
        f = cls(q=_clean(q), subject=_clean(subject), sender=_clean(sender), product=_clean(product))
        statuses = tuple(dict.fromkeys(s for v in status or [] for s in v.split(",") if s))
        unknown = [s for s in statuses if s not in STATUS_LABELS]
        if unknown:
            raise SearchError(f"unknown status: {', '.join(unknown)}")
        sources = tuple(dict.fromkeys(s for v in source or [] for s in v.split(",") if s))
        unknown = [s for s in sources if s not in SOURCE_LABELS]
        if unknown:
            raise SearchError(f"unknown source: {', '.join(unknown)}")
        f.statuses, f.sources = statuses, sources
        f.created_from, f.created_to = _utc(created_from), _utc(created_to)
        if f.created_from and f.created_to and f.created_from > f.created_to:
            raise SearchError("'received from' is after 'received to'")
        f.sort = sort or "newest"
        if f.sort not in SORTS:
            raise SearchError(f"unknown sort '{f.sort}'")
        return f


def _conditions(f: Filters) -> list[Any]:
    cond: list[Any] = []
    if f.q:
        for word in f.q.split()[:8]:  # every word must match somewhere
            pattern = _like(word)
            cond.append(or_(
                Job.subject.ilike(pattern, escape="\\"),
                Job.sender.ilike(pattern, escape="\\"),
                Job.body_text.ilike(pattern, escape="\\"),
                exists().where(JobItem.job_id == Job.id, JobItem.product_id.ilike(pattern, escape="\\")),
            ))
    if f.subject:
        cond.append(Job.subject.ilike(_like(f.subject), escape="\\"))
    if f.sender:
        cond.append(Job.sender.ilike(_like(f.sender), escape="\\"))
    if f.product:
        cond.append(exists().where(JobItem.job_id == Job.id, JobItem.product_id.ilike(_like(f.product), escape="\\")))
    if f.statuses:
        cond.append(Job.status.in_(f.statuses))
    if f.sources:
        cond.append(Job.source.in_(f.sources))
    if f.created_from:
        cond.append(Job.created_at >= f.created_from)
    if f.created_to:
        cond.append(Job.created_at <= f.created_to)
    return cond


async def search(session: AsyncSession, f: Filters, page: int, page_size: int) -> tuple[list[Job], int, int]:
    """(jobs on the page, total matches, the page actually returned)."""
    where = and_(*_conditions(f)) if _conditions(f) else None
    count_q = select(func.count()).select_from(Job)
    if where is not None:
        count_q = count_q.where(where)
    total = (await session.execute(count_q)).scalar_one()
    pages = max(1, -(-total // page_size))
    page = min(page, pages)  # a page past the end (e.g. after deleting) shows the last page
    query: Select[Any] = select(Job).order_by(SORTS[f.sort][1], desc(Job.created_at))
    if where is not None:
        query = query.where(where)
    query = query.offset((page - 1) * page_size).limit(page_size)
    jobs = list((await session.execute(query)).scalars())
    return jobs, total, page


async def facets(session: AsyncSession) -> dict[str, Any]:
    status_counts = dict((await session.execute(select(Job.status, func.count()).group_by(Job.status))).all())
    source_counts = dict((await session.execute(select(Job.source, func.count()).group_by(Job.source))).all())
    first, last = (await session.execute(select(func.min(Job.created_at), func.max(Job.created_at)))).one()
    return {
        "statuses": [{"value": k, "label": v, "count": status_counts.get(k, 0)} for k, v in STATUS_LABELS.items()],
        "sources": [{"value": k, "label": v, "count": source_counts.get(k, 0)} for k, v in SOURCE_LABELS.items()],
        "sorts": [{"value": k, "label": v[0]} for k, v in SORTS.items()],
        "page_sizes": list(PAGE_SIZES),
        "default_page_size": DEFAULT_PAGE_SIZE,
        "received": {"first": first, "last": last},
        "max_text": MAX_TEXT,
        "fields": [{"value": k, "label": v} for k, v in FIELD_LABELS.items()],
        "date_presets": [{"value": k, "label": label, "days": days} for k, label, days in DATE_PRESETS],
    }


async def suggest(session: AsyncSession, q: str, limit: int = SUGGEST_LIMIT) -> list[dict[str, Any]]:
    """Distinct subjects, senders and product IDs that contain the text, most used first."""
    term = _clean(q)
    if len(term) < 2:
        return []
    pattern = _like(term)
    per = max(2, limit // 2)
    out: list[dict[str, Any]] = []
    for field, column, model in (("product", JobItem.product_id, JobItem), ("subject", Job.subject, Job),
                                 ("sender", Job.sender, Job)):
        rows = (await session.execute(
            select(column, func.count()).select_from(model).where(column.ilike(pattern, escape="\\"))
            .group_by(column).order_by(desc(func.count()), asc(column)).limit(per))).all()
        out += [{"field": field, "label": FIELD_LABELS[field], "value": value, "count": count}
                for value, count in rows if value]
    term_low = term.lower()
    out.sort(key=lambda s: (not str(s["value"]).lower().startswith(term_low), -s["count"]))
    return out[:limit]

