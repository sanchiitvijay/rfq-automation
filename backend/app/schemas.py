"""Request/response bodies (pydantic)."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class CreateJob(BaseModel):
    source: str = Field(default="paste", pattern="^(extension|paste|upload|mailbot)$")
    raw_eml_b64: str | None = None
    subject: str = Field(default="", max_length=1000)
    sender: str = Field(default="", max_length=1000)
    body_text: str = Field(default="", max_length=200_000)
    gmail_msg_id: str | None = Field(default=None, max_length=64)
    extract_warnings: list[str] = Field(default_factory=list, max_length=10)
    force: bool = False  # re-run even if this Gmail message was already submitted


class CellEdit(BaseModel):
    product_id: str = Field(max_length=100)
    column: str = Field(max_length=60)
    value: str = Field(default="", max_length=2000)
    note: str = Field(default="", max_length=300)


class RowRemoval(BaseModel):
    product_id: str = Field(max_length=100)
    reason: str = Field(min_length=3, max_length=300)


class SheetPatch(BaseModel):
    version: int
    edits: list[CellEdit] = Field(default_factory=list, max_length=500)
    remove_rows: list[RowRemoval] = Field(default_factory=list, max_length=100)


class SendRequest(BaseModel):
    to: EmailStr
    cc: list[EmailStr] = Field(default_factory=list, max_length=10)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20_000)
    confirm_incomplete: bool = False
    resend: bool = False
    idempotency_key: str = Field(min_length=8, max_length=100)
