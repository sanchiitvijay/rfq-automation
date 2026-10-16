"""Database tables.

The editable RFQ lives in jobs.sheet (JSON, the rfq.models.Sheet shape) together with an integer
version: one atomic, versioned document makes optimistic locking simple and lets the Excel file be
regenerated from it at any time. Every human change is also logged row by row in job_edits.

Only portable column types are used (JSON, Uuid, UTCDateTime), so the same models run on SQLite
(the default) and on Postgres.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, TypeDecorator, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base

JOB_STATUSES = ("queued", "running", "needs_review", "ready", "sending", "sent", "failed")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores UTC without a zone (SQLite has no zone type) and always returns timezone-aware UTC,
    so the API never sends a time the browser would read as local time."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc)
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(20))  # extension | paste | upload | mailbot
    subject: Mapped[str] = mapped_column(Text, default="")
    sender: Mapped[str] = mapped_column(Text, default="")
    email_date: Mapped[str] = mapped_column(Text, default="")
    message_id: Mapped[str] = mapped_column(Text, default="")
    gmail_msg_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    body_text: Mapped[str] = mapped_column(Text, default="")
    raw_eml: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    attachments: Mapped[list] = mapped_column(JSON, default=list)  # attachment file names
    status: Mapped[str] = mapped_column(String(20), default="queued")
    phase: Mapped[str] = mapped_column(Text, default="Queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    sheet: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, index=True)

    items: Mapped[list[JobItem]] = relationship(back_populates="job", cascade="all, delete-orphan",
                                                order_by="JobItem.position")
    events: Mapped[list[JobEvent]] = relationship(cascade="all, delete-orphan", order_by="JobEvent.id")
    edits: Mapped[list[JobEdit]] = relationship(cascade="all, delete-orphan", order_by="JobEdit.id")
    sends: Mapped[list[JobSend]] = relationship(cascade="all, delete-orphan", order_by="JobSend.id")

    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_created", "created_at"),
        Index("ix_jobs_source", "source"),
    )


class JobItem(Base):
    """What the email asked for and how the first automatic lookup went."""

    __tablename__ = "job_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    raw_token: Mapped[str] = mapped_column(Text)
    product_id: Mapped[str] = mapped_column(Text, index=True)  # searched from the jobs list
    kind: Mapped[str] = mapped_column(String(20))
    qty: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(Text, default="body")
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    lookup_status: Mapped[str] = mapped_column(String(20), default="")
    lookup_source: Mapped[str] = mapped_column(String(20), default="none")
    notes: Mapped[str] = mapped_column(Text, default="")

    job: Mapped[Job] = relationship(back_populates="items")


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    phase: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, default="")


class JobEdit(Base):
    __tablename__ = "job_edits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[str] = mapped_column(Text)
    column: Mapped[str] = mapped_column(Text)
    old: Mapped[str] = mapped_column(Text, default="")
    new: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    user: Mapped[str] = mapped_column(Text, default="")
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JobSend(Base):
    __tablename__ = "job_sends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    to: Mapped[str] = mapped_column(Text)
    cc: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    user: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | sending | sent | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
