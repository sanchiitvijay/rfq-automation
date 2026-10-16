"""Shared helpers for the core tests."""
from __future__ import annotations

import asyncio
import gzip
import io
import sys
from email.message import EmailMessage
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rfq.config import RunOptions  # noqa: E402
from rfq.pipeline import RunResult, run  # noqa: E402

EMAILS = ROOT / "emails"
REFERENCE = ROOT / "reference" / "email-1 reference output.xlsx"
FIXTURES = Path(__file__).parent / "fixtures"
OFFLINE = RunOptions(offline=True, use_llm=False, use_pdfs=False, embed_images=False)  # no network in tests


def eml(name: str) -> bytes:
    return next(EMAILS.glob(f"{name}*.eml")).read_bytes()


def live_html(name: str) -> str:
    return gzip.decompress((FIXTURES / "live" / f"{name}.html.gz").read_bytes()).decode("utf-8")


def make_eml(body: str = "", html: str | None = None, attachments: list[tuple[str, bytes, str]] | None = None,
             subject: str = "RFQ test") -> bytes:
    msg = EmailMessage()
    msg["From"] = "Buyer <buyer@example.com>"
    msg["To"] = "rfq@example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = "<test@example.com>"
    if html is not None and not body:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(body)
        if html is not None:
            msg.add_alternative(html, subtype="html")
    for name, data, ctype in attachments or []:
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return bytes(msg)


def xlsx_bytes(rows: list[list[object]], sheets: int = 1) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    for i in range(sheets):
        ws = wb.active if i == 0 else wb.create_sheet(f"S{i}")
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def run_sync(tmp_path: Path, raw: bytes, opts: RunOptions = OFFLINE, **kwargs) -> RunResult:
    return asyncio.run(run(tmp_path, opts, raw_eml=raw, **kwargs))
