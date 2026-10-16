from __future__ import annotations

import asyncio
import base64

import pytest
from backend_helpers import drain

EMAILS = __import__("pathlib").Path(__file__).resolve().parents[2] / "emails"
pytestmark = pytest.mark.asyncio


def raw(name: str) -> str:
    return base64.b64encode(next(EMAILS.glob(f"{name}*.eml")).read_bytes()).decode()


async def make_job(client, queue, ctx, name="email-3", **extra):
    r = await client.post("/api/jobs", json={"source": "extension", "raw_eml_b64": raw(name), **extra})
    assert r.status_code == 201, r.text
    await drain(queue, ctx)
    return r.json()["job_id"]


async def test_auth_required(env):
    client, *_ = env
    assert (await client.get("/api/jobs", headers={"X-API-Key": "nope"})).status_code == 401


async def test_create_run_and_detail(env):
    client, queue, ctx, _ = env
    jid = await make_job(client, queue, ctx)
    d = (await client.get(f"/api/jobs/{jid}")).json()
    assert d["status"] == "needs_review" and d["version"] == 1
    assert d["requested"] == 7 and d["not_found"] == 3
    assert [i["product_id"] for i in d["items"]][-1] == "MTX-4409-XQ"
    assert any(e["phase"] == "Done" for e in d["events"])
    x = await client.get(f"/api/jobs/{jid}/rfq.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


async def test_gmail_id_is_idempotent(env):
    client, queue, ctx, _ = env
    body = {"source": "extension", "raw_eml_b64": raw("email-1"), "gmail_msg_id": "msg-f:1"}
    a = (await client.post("/api/jobs", json=body)).json()
    b = (await client.post("/api/jobs", json=body)).json()
    assert a["job_id"] == b["job_id"] and b["created"] is False and len(queue.jobs) == 1
    c = (await client.post("/api/jobs", json={**body, "force": True})).json()
    assert c["created"] and c["job_id"] != a["job_id"]


async def test_bad_inputs(env):
    client, *_ = env
    assert (await client.post("/api/jobs", json={"source": "paste", "body_text": "  "})).status_code == 422
    assert (await client.post("/api/jobs", json={"source": "extension", "raw_eml_b64": base64.b64encode(b"no headers here").decode()})).status_code == 422
    r = await client.post("/api/jobs/upload", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 422


async def test_paste_job(env):
    client, queue, ctx, _ = env
    r = await client.post("/api/jobs", json={"source": "paste", "subject": "RFQ", "sender": "a@b.com", "body_text": "5106912\n5106935"})
    await drain(queue, ctx)
    d = (await client.get(f"/api/jobs/{r.json()['job_id']}")).json()
    assert d["found"] == 2 and d["email"]["has_raw"] is False


async def test_edit_validation_and_locking(env):
    client, queue, ctx, _ = env
    jid = await make_job(client, queue, ctx)
    s = (await client.get(f"/api/jobs/{jid}/sheet")).json()
    pid = next(r["product_id"] for r in s["rows"] if r["lookup_status"] == "Found" and "Weight" not in r["cells"])
    ok = await client.patch(f"/api/jobs/{jid}/sheet", json={"version": 1, "edits": [
        {"product_id": pid, "column": "Weight", "value": "12.5 lb", "note": "quote"}]})
    assert ok.status_code == 200 and ok.json()["version"] == 2
    cell = next(r for r in ok.json()["rows"] if r["product_id"] == pid)["cells"]["Weight"]
    assert cell["source_type"] == "manual_edit" and "Tester" in cell["source"]
    stale = await client.patch(f"/api/jobs/{jid}/sheet", json={"version": 1, "edits": [
        {"product_id": pid, "column": "Weight", "value": "13 lb"}]})
    assert stale.status_code == 409 and stale.json()["current_version"] == 2
    a, b = await asyncio.gather(*[client.patch(f"/api/jobs/{jid}/sheet", json={"version": 2, "edits": [
        {"product_id": pid, "column": "Weight", "value": v}]}) for v in ("13 lb", "14 lb")])
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    for bad in ("heavy", "=1+1", "12"):
        r = await client.patch(f"/api/jobs/{jid}/sheet", json={"version": 3, "edits": [
            {"product_id": pid, "column": "Weight", "value": bad}]})
        assert r.status_code == 422, bad
    r = await client.patch(f"/api/jobs/{jid}/sheet", json={"version": 3, "edits": [
        {"product_id": pid, "column": "product_id", "value": "1"}]})
    assert r.status_code == 422


async def test_fill_not_found_and_remove_row(env):
    client, queue, ctx, _ = env
    jid = await make_job(client, queue, ctx)
    r = await client.patch(f"/api/jobs/{jid}/sheet", json={"version": 1, "edits": [
        {"product_id": "MTX-4409-XQ", "column": "Description", "value": "Matched by phone", "note": "customer"}],
        "remove_rows": [{"product_id": "31-024", "reason": "dropped"}]})
    rows = {x["product_id"]: x for x in r.json()["rows"]}
    assert rows["MTX-4409-XQ"]["lookup_status"] == "Manual" and "31-024" not in rows
    d = (await client.get(f"/api/jobs/{jid}")).json()
    assert any("Removed from the RFQ by Tester: dropped" in n["note"] for n in d["notes"])


async def test_send_flow(env):
    client, queue, ctx, sent = env
    jid = await make_job(client, queue, ctx)
    base = {"to": "priya.nair@sourcing.example.com", "subject": "Re: RFQ", "body": "attached",
            "idempotency_key": "key-00000001"}
    assert (await client.post(f"/api/jobs/{jid}/send", json={**base, "to": "nope"})).status_code == 422
    incomplete = await client.post(f"/api/jobs/{jid}/send", json=base)
    assert incomplete.status_code == 409
    a, b = await asyncio.gather(*[client.post(f"/api/jobs/{jid}/send", json={**base, "confirm_incomplete": True})
                                  for _ in range(2)])
    assert {a.status_code, b.status_code} == {202} and a.json()["id"] == b.json()["id"]
    await drain(queue, ctx)
    assert len(sent) == 1
    msg = sent[0]
    assert msg["To"] == "priya.nair@sourcing.example.com" and msg["In-Reply-To"] == "<rfq-sample-3@sourcing.example.com>"
    assert [p.get_filename() for p in msg.iter_attachments()] == ["RFQ.xlsx"]
    d = (await client.get(f"/api/jobs/{jid}")).json()
    assert d["status"] == "sent" and d["sends"][0]["status"] == "sent"
    again = await client.post(f"/api/jobs/{jid}/send", json={**base, "idempotency_key": "key-00000002", "confirm_incomplete": True})
    assert again.status_code == 409
    resend = await client.post(f"/api/jobs/{jid}/send", json={**base, "idempotency_key": "key-00000003",
                                                              "confirm_incomplete": True, "resend": True})
    assert resend.status_code == 202
    await drain(queue, ctx)
    assert len(sent) == 2


async def test_send_permanent_failure_returns_to_review(env, monkeypatch):
    client, queue, ctx, _ = env
    from backend.app import worker as worker_mod
    from backend.app.services.mail import PermanentSendError

    def fail(settings, msg):
        raise PermanentSendError("Gmail login failed")

    monkeypatch.setattr(worker_mod, "smtp_send", fail)
    jid = await make_job(client, queue, ctx)
    await client.post(f"/api/jobs/{jid}/send", json={"to": "a@example.com", "subject": "s", "body": "b",
                                                     "idempotency_key": "key-fail-0001", "confirm_incomplete": True})
    await drain(queue, ctx)
    d = (await client.get(f"/api/jobs/{jid}")).json()
    assert d["status"] == "needs_review" and "Gmail login failed" in d["error"] and d["sends"][0]["status"] == "failed"


async def test_recipient_domain_allowlist(env, monkeypatch):
    client, queue, ctx, _ = env
    from backend.app.settings import get_settings

    monkeypatch.setenv("ALLOWED_RECIPIENT_DOMAINS", "sourcing.example.com")
    get_settings.cache_clear()
    jid = await make_job(client, queue, ctx)
    r = await client.post(f"/api/jobs/{jid}/send", json={"to": "x@evil.example.org", "subject": "s", "body": "b",
                                                         "idempotency_key": "key-dom-00001", "confirm_incomplete": True})
    assert r.status_code == 422 and "not an allowed" in r.json()["detail"]


async def test_worker_failure_retries_then_fails(env, monkeypatch):
    client, queue, ctx, _ = env
    from arq import Retry

    from backend.app import worker as worker_mod

    async def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(worker_mod, "run", boom)
    r = await client.post("/api/jobs", json={"source": "paste", "body_text": "5106912"})
    jid = r.json()["job_id"]
    name, args = queue.jobs.pop(0)
    with pytest.raises(Retry):
        await worker_mod.run_rfq_job({**ctx, "job_try": 1}, *args)
    assert (await client.get(f"/api/jobs/{jid}")).json()["status"] == "queued"
    await worker_mod.run_rfq_job({**ctx, "job_try": 2}, *args)
    d = (await client.get(f"/api/jobs/{jid}")).json()
    assert d["status"] == "failed" and "disk full" in d["error"]
    assert (await client.post(f"/api/jobs/{jid}/retry")).status_code == 200


async def test_delete_job(env):
    client, queue, ctx, _ = env
    jid = await make_job(client, queue, ctx, name="email-1")
    assert (await client.delete(f"/api/jobs/{jid}")).status_code == 204
    assert (await client.get(f"/api/jobs/{jid}")).status_code == 404


async def test_job_saved_without_queue_is_recovered_later(env):
    from sqlalchemy import text

    from backend.app import db
    from backend.app import worker as worker_mod
    from backend.app.main import app

    client, queue, ctx, _ = env
    app.state.queue = None  # Redis down when the email arrives
    r = await client.post("/api/jobs", json={"source": "paste", "body_text": "5106912"})
    assert r.status_code == 201 and r.json()["queued"] is False and "starts automatically" in r.json()["message"]
    jid = r.json()["job_id"]
    async with db.engine().begin() as conn:  # pretend it has been waiting for 2 minutes
        await conn.execute(text("UPDATE jobs SET updated_at = now() - interval '2 minutes' WHERE id = :id"), {"id": jid})
    assert await worker_mod.recover_stuck_jobs({**ctx, "redis": queue}) == "requeued 1"
    await drain(queue, ctx)
    assert (await client.get(f"/api/jobs/{jid}")).json()["status"] == "needs_review"


async def test_job_queued_twice_runs_once(env):
    from backend.app import worker as worker_mod

    client, queue, ctx, _ = env
    r = await client.post("/api/jobs", json={"source": "paste", "body_text": "5106912"})
    name, args = queue.jobs.pop(0)
    first, second = await asyncio.gather(worker_mod.run_rfq_job(ctx, *args), worker_mod.run_rfq_job(ctx, *args))
    assert sorted([first, second]) == ["done", "skipped (already taken, finished or deleted)"]
    d = (await client.get(f"/api/jobs/{r.json()['job_id']}")).json()
    assert d["status"] == "needs_review" and d["version"] == 1
