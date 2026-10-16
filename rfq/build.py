"""Base flow CLI (the contract mailbot.py relies on):

    python rfq/build.py <email.eml> --out out [--offline] [--no-llm] [--no-pdf]

Writes out/<email name>/RFQ.xlsx and out/<email name>/reply.eml.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make the repo root importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rfq.config import RunOptions  # noqa: E402
from rfq.lookup.cache import make_cache  # noqa: E402
from rfq.parse_email import EmailTooLarge  # noqa: E402
from rfq.pipeline import run  # noqa: E402


async def _print_progress(event: dict) -> None:
    eta = f" (~{event['eta_seconds']} s left)" if event["eta_seconds"] else ""
    print(f"[{event['progress']:3d}%] {event['message']}{eta}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an RFQ workbook from a request email.")
    parser.add_argument("email", type=Path, help="the request email (.eml)")
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--offline", action="store_true", help="backup catalog + spec sheets only, no Chrome")
    parser.add_argument("--no-llm", action="store_true", help="skip the AI contradiction check")
    parser.add_argument("--no-pdf", action="store_true", help="do not read spec sheet PDFs")
    parser.add_argument("--no-images", action="store_true", help="do not embed product pictures in the Excel")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    if not args.email.is_file():
        print(f"Email file not found: {args.email}", file=sys.stderr)
        return 2
    opts = RunOptions(offline=args.offline, use_llm=not args.no_llm, use_pdfs=not args.no_pdf,
                      embed_images=not args.no_images)

    async def go() -> int:
        cache = await make_cache()
        try:
            result = await run(args.out / args.email.stem, opts, raw_eml=args.email.read_bytes(),
                               progress_cb=None if args.quiet else _print_progress, cache=cache)
        except EmailTooLarge as e:
            print(str(e), file=sys.stderr)
            return 2
        rows = result.sheet.rows
        found = sum(1 for r in rows if r.lookup_status != "Not found")
        print(f"RFQ saved: {result.xlsx_path}  ({found}/{len(rows)} found, fill rate {result.report.fill_overall}%, "
              f"{len(result.report.flags)} flags; AI check: {result.report.llm_status})")
        return 0

    return asyncio.run(go())


if __name__ == "__main__":
    sys.exit(main())
