"""Shared API key for the extension and the frontend (header X-API-Key, or ?key= for SSE/downloads,
because EventSource and plain links cannot send headers)."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Query, status

from backend.app.settings import get_settings


def require_key(x_api_key: str | None = Header(default=None), key: str | None = Query(default=None)) -> None:
    supplied = x_api_key or key or ""
    if not hmac.compare_digest(supplied.encode(), get_settings().api_key.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or wrong API key")


def current_user(x_user: str | None = Header(default=None)) -> str:
    name = (x_user or "").strip()[:80]
    return name or get_settings().default_user
