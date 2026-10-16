"""The RFQ flow end to end. The CLI, the backend worker and (later) the Azure function all call run()."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rfq.config import RunOptions
from rfq.eta import Progress, ProgressFn
from rfq.excel.writer import render
from rfq.extract_ids import extract
from rfq.lookup import catalog
from rfq.lookup.cache import Cache, MemoryCache
from rfq.lookup.resolve import resolve
from rfq.models import ParsedEmail, QualityReport, RequestItem, Sheet
from rfq.parse_email import parse_eml, parse_text
from rfq.quality.agent import run_quality
from rfq.quality.llm_checks import BATCH_SIZE
from rfq.reply import write_reply


@dataclass
class RunResult:
    email: ParsedEmail
    items: list[RequestItem]
    sheet: Sheet
    report: QualityReport
    xlsx_path: Path
    reply_path: Path


def email_info(parsed: ParsedEmail) -> dict[str, str]:
    return {"subject": parsed.subject, "sender": parsed.sender}


async def run(out_dir: Path, opts: RunOptions, *, raw_eml: bytes | None = None, text: str | None = None,
              subject: str = "", sender: str = "", progress_cb: ProgressFn | None = None,
              cache: Cache | None = None, llm_client: Any | None = None,
              xlsx_name: str = "RFQ.xlsx") -> RunResult:
    if raw_eml is None and text is None:
        raise ValueError("run() needs raw_eml or text")
    cache = cache or MemoryCache()
    progress = Progress(progress_cb, cache)
    await progress.load()
    progress.plan("parse", 2)
    progress.plan("live" if not opts.offline else "catalog", 6)  # rough guess until the IDs are known
    progress.plan("write", 1)
    await progress.start("parse", "Parsing email")
    parsed = parse_eml(raw_eml) if raw_eml is not None else parse_text(text or "", subject, sender)
    await progress.step("parse", "Extracting IDs")
    extracted = extract(parsed.body, parsed.attachments)
    await progress.finish("parse")
    ferguson = [i for i in extracted.items if i.kind == "ferguson"]
    links = catalog.spec_sheet_links()
    if opts.offline:
        progress.plan("catalog", len(ferguson))
    else:
        if opts.serpapi_key:
            progress.plan("serp", len(ferguson))
        progress.plan("live", len(ferguson))  # refined once SerpApi has answered
        progress.floor("live", 60.0 / opts.ferguson_rate_per_minute)
    progress.plan("pdf", sum(1 for i in ferguson if i.product_id in links) // 3 if opts.use_pdfs else 0)
    progress.plan("fill", 1)
    progress.plan("quality", 1)
    progress.plan("llm", math.ceil(len(ferguson) / BATCH_SIZE) if opts.use_llm else 0)
    progress.plan("write", 1)

    sheet = await resolve(extracted.items, opts, cache, progress)
    sheet.warnings[:0] = parsed.warnings + extracted.warnings

    report = await run_quality(sheet, opts, cache, llm_client, progress=progress)

    await progress.start("write", "Writing RFQ and summary")
    folder = out_dir
    xlsx = render(sheet, folder / xlsx_name, report, email_info(parsed))
    reply = write_reply(sheet, report, xlsx, folder / "reply.eml", parsed.subject)
    await progress.finish("write")
    found = sum(1 for r in sheet.rows if r.lookup_status != "Not found")
    await progress.done(f"Done: {found}/{len(sheet.rows)} found, fill rate {report.fill_overall}%")
    return RunResult(parsed, extracted.items, sheet, report, xlsx, reply)
