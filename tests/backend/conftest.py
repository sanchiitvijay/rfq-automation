"""Backend tests: real Postgres (database rfq_test), fake queue, fake SMTP, offline lookups."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import tempfile

_DB = Path(tempfile.mkdtemp(prefix="rfq-test-")) / "test.sqlite3"
os.environ.update({
    "DATABASE_URL": f"sqlite+aiosqlite:///{_DB}",
    "API_KEY": "test-key",
    "RFQ_OFFLINE": "true",
    "RFQ_USE_LLM": "false",
    "RFQ_EMBED_IMAGES": "false",
    "BOT_EMAIL": "rfq-bot@example.com",
    "ALLOWED_RECIPIENT_DOMAINS": "",
})
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402

from backend.app import db, events  # noqa: E402
from backend.app import worker as worker_mod  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.settings import get_settings  # noqa: E402
from rfq.lookup.cache import MemoryCache  # noqa: E402
from backend_helpers import FakeQueue  # noqa: E402

H = {"X-API-Key": "test-key", "X-User": "Tester"}


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "jobs"))
    get_settings.cache_clear()

    async def no_publish(*a, **k):
        return None

    monkeypatch.setattr(events, "publish", no_publish)
    monkeypatch.setattr(worker_mod.events, "publish", no_publish)
    sent: list = []
    monkeypatch.setattr(worker_mod, "smtp_send", lambda settings, msg: (sent.append(msg), str(msg["Message-ID"]))[1])

    await db.create_tables()
    async with db.engine().begin() as conn:
        for table in ("job_sends", "job_edits", "job_events", "job_items", "jobs"):
            await conn.execute(text(f"DELETE FROM {table}"))
    queue = FakeQueue()
    app.state.queue, app.state.cache = queue, MemoryCache()
    ctx = {"cache": MemoryCache(), "job_try": 1}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=H) as client:
        yield client, queue, ctx, sent
    await db.dispose()
    get_settings.cache_clear()
