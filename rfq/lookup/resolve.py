"""Builds one RFQ row per requested product.

Order for a Ferguson ID (live mode):
  1. SerpApi (Google)    – confirms the product on ferguson.com + page URL / price, no ferguson.com hit
  2. product page        – read through Chrome, rate limited (FERGUSON_RATE_PER_MINUTE, default 12/min).
                           Only when SerpApi is not configured / used up / found nothing, or when the
                           backup catalog does not have the product (SerpApi gives no specs).
  3. backup catalog      – specs collected 2026-09-24
  4. Not found           – with every source that was tried
Then blank cells are filled from spec sheets. Live page wins over the catalog; differences are noted.
"""
from __future__ import annotations

import asyncio
import re

import httpx

from rfq.config import STATUS_FOUND, RunOptions
from rfq.eta import Progress
from rfq.lookup import catalog
from rfq.lookup.cache import Cache
from rfq.lookup.live import LiveFerguson, LiveResult, LiveUnavailable
from rfq.lookup.serpapi import SerpApi, SerpResult
from rfq.lookup.specsheet import read_spec_sheet
from rfq.models import Cell, RequestItem, Row, Sheet

PDF_FIELDS = ("Thickness", "ASTM")
COMPETITOR_REASON = ("competitor or unknown part number, not a Ferguson product ID; not searched on the web "
                     "(the competitor finder is not part of this version)")


def _norm(value: str) -> str:
    return re.sub(r"[\s.\"']", "", value).lower()


def _same(live: str, cat: str) -> bool:
    a, b = _norm(live), _norm(cat)
    if a == b:
        return True
    # catalog "3" vs live "3 in": same number, the catalog just left the unit out
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([a-z]+)", a)
    return bool(m and b == m.group(1))


def _new_row(item: RequestItem) -> Row:
    return Row(product_id=item.product_id, kind=item.kind, raw_token=item.raw_token,
               context=item.context, qty=item.qty)


def _merge_supplier(row: Row, *layers: dict[str, Cell]) -> None:
    """Later layers win (live page > SerpApi > catalog)."""
    merged: dict[str, Cell] = {}
    for layer in layers:
        merged.update(layer)
    row.supplier = merged


def _apply_catalog(row: Row, why: str | None, sheet: Sheet, serp: SerpResult | None = None) -> None:
    row.cells = catalog.cells(row.product_id)
    serp_supplier = serp.supplier if serp and serp.status == "found" else {}
    _merge_supplier(row, catalog.supplier(row.product_id), serp_supplier)
    row.lookup_status = STATUS_FOUND
    row.lookup_source = "serpapi+catalog" if serp_supplier else "catalog"
    row.tried.append("catalog: found")
    if why:
        sheet.add_note(row.product_id, f"{why}; values taken from the backup catalog (collected 2026-09-24).")


def _merge_live(row: Row, live: LiveResult, sheet: Sheet, serp: SerpResult | None) -> None:
    row.cells = dict(live.cells)
    serp_supplier = serp.supplier if serp and serp.status == "found" else {}
    _merge_supplier(row, catalog.supplier(row.product_id), serp_supplier, live.supplier)
    row.lookup_status = STATUS_FOUND
    row.lookup_source = "cache" if live.from_cache else "live"
    row.tried.append("ferguson.com product page: read" + (" (cached)" if live.from_cache else ""))
    cat_cells = catalog.cells(row.product_id)
    for column, cat_cell in cat_cells.items():
        live_cell = row.cells.get(column)
        if live_cell is None:  # the page does not show it: keep the catalog value with its own source
            row.cells[column] = cat_cell
        elif not _same(live_cell.value, cat_cell.value):
            sheet.add_note(row.product_id, f"{column}: live page says '{live_cell.value[:120]}' (used), "
                                           f"backup catalog says '{cat_cell.value[:120]}'.")
    if not cat_cells:
        sheet.add_note(row.product_id, "Not in the backup catalog; all values read live from ferguson.com.")


def _apply_serp_only(row: Row, serp: SerpResult, page_why: str, sheet: Sheet) -> None:
    """On ferguson.com according to Google, but no specs anywhere: identity only, specs stay blank."""
    row.cells = {}
    if serp.title and not serp.title_truncated:
        row.cells["Description"] = Cell(serp.title, "serpapi", "medium",
                                        "Title of the ferguson.com product page in Google (via SerpApi)", serp.url)
    _merge_supplier(row, serp.supplier)
    row.lookup_status, row.lookup_source = STATUS_FOUND, "serpapi"
    sheet.add_note(row.product_id, f"Found on ferguson.com via SerpApi, but the product page could not be read "
                                   f"({page_why}) and it is not in the backup catalog: specs left blank.")


def _not_found(row: Row, reason: str, sheet: Sheet) -> None:
    row.not_found_reason = reason
    sheet.add_note(row.product_id, f"Not found: {reason}.")


def _needs_page(pid: str, serp: SerpResult | None, policy: str) -> bool:
    if serp is None or serp.status != "found":
        return True  # SerpApi off, used up, failed or found nothing: read the page ourselves
    if policy == "always":
        return True
    if policy == "never":
        return False
    return not catalog.has(pid)  # "missing": SerpApi has no specs, so read the page only if the catalog can't help


async def _serp_lookups(pids: list[str], opts: RunOptions, cache: Cache, progress: Progress,
                        sheet: Sheet) -> dict[str, SerpResult]:
    api = SerpApi(opts.serpapi_key, cache, timeout_s=opts.serpapi_timeout_s)
    ok, why = await api.enabled()
    if not ok:
        sheet.warnings.append(f"SerpApi not used ({why}); products were read from ferguson.com directly "
                              f"(max {opts.ferguson_rate_per_minute} page loads per minute).")
        return {}
    progress.plan("serp", len(pids))
    await progress.start("serp", "Searching ferguson.com via SerpApi")
    results: dict[str, SerpResult] = {}
    sem = asyncio.Semaphore(8)  # SerpApi answers slowly but in parallel; its hourly limit is far above this
    async with httpx.AsyncClient() as client:
        api._client = client

        async def one(pid: str) -> None:
            async with sem:
                results[pid] = await api.search(pid)
            await progress.step("serp", f"Searching ferguson.com via SerpApi ({len(results)}/{len(pids)})")

        await asyncio.gather(*(one(p) for p in pids))
    await progress.finish("serp")
    exhausted = [r for r in results.values() if r.status in ("exhausted", "disabled")]
    if exhausted:
        sheet.warnings.append(f"SerpApi stopped during this run ({exhausted[0].reason}); the remaining products "
                              "were read from ferguson.com directly.")
    return results


async def _page_lookups(pids: list[str], opts: RunOptions, cache: Cache, progress: Progress,
                        sheet: Sheet) -> dict[str, LiveResult] | None:
    cached = sum([1 for p in pids if await cache.get_json(f"lookup:{p}")])
    progress.plan("live", len(pids) - cached)
    progress.plan("catalog", cached)
    progress.floor("live", 60.0 / opts.ferguson_rate_per_minute)
    await progress.start("live", "Reading ferguson.com product pages")
    try:
        async with LiveFerguson(opts.cdp_url, cache, opts.live_timeout_s, opts.live_concurrency,
                                opts.ferguson_rate_per_minute) as live:
            results: dict[str, LiveResult] = {}

            async def one(pid: str) -> None:
                results[pid] = await live.lookup(pid)
                # cache hits are near-instant; count them separately so they do not skew the time estimate
                await progress.step("catalog" if results[pid].from_cache else "live",
                                    f"Reading ferguson.com product pages ({len(results)}/{len(pids)})")

            await asyncio.gather(*(one(p) for p in pids))
            if live.waited_s >= 5:
                sheet.warnings.append(f"Waited {live.waited_s:.0f} s in total for the ferguson.com rate limit "
                                      f"({opts.ferguson_rate_per_minute} page loads per minute).")
            return results
    except LiveUnavailable as e:
        sheet.warnings.append(f"Product pages could not be read: {e}. Backup catalog used instead.")
        return None
    finally:
        await progress.finish("live")
        await progress.finish("catalog")


def _serp_tried(serp: SerpResult | None) -> str | None:
    if serp is None:
        return None
    label = {"found": "found the product page", "no_result": serp.reason, "exhausted": serp.reason,
             "error": serp.reason, "disabled": serp.reason}[serp.status]
    return f"SerpApi (Google): {label}" + (" (cached)" if serp.from_cache else "")


async def resolve(items: list[RequestItem], opts: RunOptions, cache: Cache, progress: Progress) -> Sheet:
    sheet = Sheet(mode="offline" if opts.offline else "live")
    rows = [_new_row(i) for i in items]
    by_item = list(zip(items, rows))
    for item, row in by_item:
        if item.occurrences > 1:
            sheet.add_note(row.product_id, f"Listed {item.occurrences} times in the request; kept once.")
        if item.kind == "competitor":
            row.tried.append("not a Ferguson ID")
            brand = f" (brand in the email: {item.brand})" if item.brand else ""
            _not_found(row, f"{COMPETITOR_REASON}{brand}", sheet)

    ferguson = [r for i, r in by_item if i.kind == "ferguson"]
    pids = [r.product_id for r in ferguson]
    serp: dict[str, SerpResult] = {}
    pages: dict[str, LiveResult] | None = None
    page_pids: list[str] = []
    if pids and not opts.offline:
        serp = await _serp_lookups(pids, opts, cache, progress, sheet)
        page_pids = [p for p in pids if _needs_page(p, serp.get(p), opts.scrape_after_serpapi)]
        progress.plan("live", len(page_pids))
        if page_pids:
            pages = await _page_lookups(page_pids, opts, cache, progress, sheet)
    else:
        progress.plan("catalog", len(pids))
        await progress.start("catalog", "Looking up products in the backup catalog")

    for row in ferguson:
        pid = row.product_id
        s = serp.get(pid)
        if (tried := _serp_tried(s)):
            row.tried.append(tried)
        page = pages.get(pid) if pages else None
        if page and page.status == "found":
            _merge_live(row, page, sheet, s)
            continue

        if opts.offline:
            row.tried.append("ferguson.com: not checked (offline mode)")
            page_why = "offline mode"
        elif pid not in page_pids:
            page_why = "not needed: SerpApi confirmed it and the catalog has the specs"
        elif page is None:
            row.tried.append("ferguson.com product page: not available (Chrome not reachable)")
            page_why = "Chrome not reachable"
        else:
            row.tried.append(f"ferguson.com product page: {page.reason}")
            page_why = page.reason

        serp_found = s is not None and s.status == "found"
        if catalog.has(pid):
            if serp_found and pid not in page_pids:
                why = None  # the normal SerpApi path: nothing to explain
                sheet.add_note(pid, "Confirmed on ferguson.com via SerpApi (page and price); specs from the backup "
                                    "catalog.")
            elif page and page.status == "not_found" and not serp_found:
                why = "ferguson.com no longer lists this product"
            elif page is not None or (pages is None and pid in page_pids):
                why = f"Product page could not be read ({page_why})"
            else:
                why = None
            _apply_catalog(row, why, sheet, s)
        elif serp_found:
            assert s is not None
            _apply_serp_only(row, s, page_why, sheet)
        else:
            row.tried.append("catalog: not listed")
            if page and page.status == "not_found":
                where = "not on ferguson.com"
            elif opts.offline:
                where = "live lookup skipped (offline mode)"
            elif page is None:
                where = "ferguson.com could not be checked (Chrome not reachable)"
            else:
                where = f"ferguson.com page could not be read ({page.reason})"
            if s is not None and s.status == "no_result":
                where += "; Google (SerpApi) has no ferguson.com page for it either"
            _not_found(row, f"{where} and not in the backup catalog", sheet)
    if opts.offline or not pids:
        await progress.finish("catalog")

    if opts.use_pdfs:
        await _fill_from_spec_sheets(rows, opts, cache, progress, sheet)
    sheet.rows = rows
    return sheet


async def _fill_from_spec_sheets(rows: list[Row], opts: RunOptions, cache: Cache, progress: Progress,
                                 sheet: Sheet) -> None:
    links = catalog.spec_sheet_links()
    todo = [r for r in rows if r.lookup_status == STATUS_FOUND and r.product_id in links
            and any(not r.value(f) for f in PDF_FIELDS)]
    if not todo:
        return
    progress.plan("pdf", len(todo))
    await progress.start("pdf", "Reading spec sheets")
    sem = asyncio.Semaphore(4)
    done = 0
    async with httpx.AsyncClient(headers={"User-Agent": "RFQ-Agent/1.0 (spec sheet reader)"}) as client:
        async def one(row: Row) -> None:
            nonlocal done
            async with sem:
                if not await cache.get_json(f"pdftext:{links[row.product_id]}"):
                    # api.ferguson.com is a Ferguson host too: PDFs share the same per-minute budget
                    await cache.rate("ferguson", opts.ferguson_rate_per_minute, 60.0)
                result = await read_spec_sheet(links[row.product_id], row.cells, cache, client)
            if not result.ok:
                sheet.add_note(row.product_id, result.reason)
            for column, cell in result.cells.items():
                row.cells[column] = cell
                sheet.add_note(row.product_id, f"{column} filled from the spec sheet (it was blank).")
            for conflict in result.conflicts:
                sheet.add_note(row.product_id, conflict)
            done += 1
            await progress.step("pdf", f"Reading spec sheets ({done}/{len(todo)})")

        await asyncio.gather(*(one(r) for r in todo))
    await progress.finish("pdf")
