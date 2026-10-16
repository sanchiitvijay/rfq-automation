"""RFQ Quality Agent: code checks + LLM contradiction check + fill rates. Flags, never overwrites.

Run on any finished workbook:  python -m rfq.quality.agent out/<email>/RFQ.xlsx [--no-llm]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from rfq.config import SPEC_COLUMNS, STATUS_NOT_FOUND, RunOptions
from rfq.eta import Progress
from rfq.lookup.cache import Cache, MemoryCache
from rfq.models import Flag, QualityReport, Sheet
from rfq.quality.checks import run_code_checks
from rfq.quality.llm_checks import run_llm_checks

_TYPE_ORDER = {"not_found": 0, "suspicious": 1, "missing": 2}


def fill_rates(sheet: Sheet, report: QualityReport) -> None:
    rows = sheet.rows
    found = [r for r in rows if r.lookup_status != STATUS_NOT_FOUND]
    total_cells = len(rows) * len(SPEC_COLUMNS)
    filled = sum(len(SPEC_COLUMNS) - len(r.missing_columns()) for r in rows)
    found_cells = len(found) * len(SPEC_COLUMNS)
    found_filled = sum(len(SPEC_COLUMNS) - len(r.missing_columns()) for r in found)
    report.fill_overall = round(100 * filled / total_cells, 1) if total_cells else 0.0
    report.fill_found = round(100 * found_filled / found_cells, 1) if found_cells else 0.0
    report.fill_by_column = {
        c: round(100 * sum(1 for r in rows if r.value(c)) / len(rows), 1) if rows else 0.0 for c in SPEC_COLUMNS
    }
    report.fill_by_product = {
        r.product_id: round(100 * (len(SPEC_COLUMNS) - len(r.missing_columns())) / len(SPEC_COLUMNS), 1)
        for r in rows
    }


def _merge(flags: list[Flag]) -> list[Flag]:
    """One flag per cell and type; reasons from code and LLM are joined."""
    merged: dict[tuple[str, str], Flag] = {}
    for f in flags:
        key = (f.cell, f.type)
        if key not in merged:
            merged[key] = Flag(**f.__dict__)
            continue
        m = merged[key]
        if f.reason not in m.reason:
            m.reason = f"{m.reason}; {f.reason}"
        if f.check != m.check:
            m.check = "code"  # code-confirmed wins in the label
    def order(f: Flag) -> tuple[int, int, int]:
        letters = "".join(ch for ch in f.cell if ch.isalpha())
        number = int("".join(ch for ch in f.cell if ch.isdigit()) or 0)
        col = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(letters)))
        return number, _TYPE_ORDER[f.type], col
    return sorted(merged.values(), key=order)


async def run_quality(sheet: Sheet, opts: RunOptions, cache: Cache | None = None, llm_client: Any | None = None,
                      llm: bool | None = None, progress: Progress | None = None,
                      llm_cache_only: bool = False) -> QualityReport:
    cache = cache or MemoryCache()
    report = QualityReport()
    if progress:
        await progress.start("quality", "Quality checks")
    flags = run_code_checks(sheet)
    if progress:
        await progress.finish("quality")
    if llm if llm is not None else opts.use_llm:
        if progress:
            await progress.start("llm", "AI contradiction check")
        llm_flags, report.llm_status = await run_llm_checks(sheet, opts.openai_model, cache, llm_client,
                                                            cache_only=llm_cache_only)
        flags.extend(llm_flags)
        if progress:
            await progress.finish("llm")
    else:
        report.llm_status = "skipped: turned off for this run (code checks still ran)"
    report.flags = _merge(flags)
    fill_rates(sheet, report)
    return report


def main(argv: list[str] | None = None) -> int:
    from rfq.excel.reader import read
    from rfq.excel.writer import render

    parser = argparse.ArgumentParser(description="Run the RFQ Quality Agent on a finished RFQ workbook.")
    parser.add_argument("xlsx", type=Path)
    parser.add_argument("--out", type=Path, help="where to save the checked workbook (default: overwrite)")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args(argv)
    try:
        sheet = read(args.xlsx)
    except (OSError, ValueError, KeyError) as e:
        print(f"Cannot read {args.xlsx}: {e}", file=sys.stderr)
        return 2
    report = asyncio.run(run_quality(sheet, RunOptions(use_llm=not args.no_llm)))
    out = render(sheet, args.out or args.xlsx, report)
    print(f"{len(report.flags)} flags, fill rate {report.fill_overall}% → {out}  (LLM: {report.llm_status})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
