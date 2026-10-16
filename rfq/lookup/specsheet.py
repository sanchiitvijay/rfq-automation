"""Reads manufacturer spec sheet PDFs and fills *blank* RFQ cells from them.

Spec sheets usually describe a whole product family ("2, 2.5, 3, 4 and 6 Mil"), so a value is only
taken when the PDF states exactly one value for the field. Every value carries the verbatim quote it
came from. Anything ambiguous stays blank.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from rfq.config import ALLOWED_HOSTS, MAX_PDF_BYTES
from rfq.lookup.cache import PDF_TTL, Cache
from rfq.models import Cell

log = logging.getLogger(__name__)

_THICKNESS_LABELED = re.compile(r"thickness\s*:?\s*\n?\s*(\d+(?:\.\d+)?)\s*mils?\b", re.IGNORECASE)
_THICKNESS_HEADING = re.compile(r"\((\d+(?:\.\d+)?)\s*MIL\)")
_THICKNESS_LIST = re.compile(r"\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)+\s*(?:,?\s*and\s*\d+(?:\.\d+)?)?\s*mils?\b",
                             re.IGNORECASE)
_ASTM = re.compile(r"ASTM\s*D\s*-?\s*(\d{3,5})(?:-\d{2})?")


@dataclass
class SpecSheetResult:
    url: str
    ok: bool
    reason: str = ""
    cells: dict[str, Cell] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)


async def fetch_text(url: str, cache: Cache, client: httpx.AsyncClient) -> str:
    cached = await cache.get_json(f"pdftext:{url}")
    if cached is not None:
        return cached
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host {host} is not on the allowlist")
    async with client.stream("GET", url, follow_redirects=True, timeout=30) as resp:
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "pdf" not in ctype:
            raise ValueError(f"not a PDF ({ctype or 'no content type'})")
        data = bytearray()
        async for chunk in resp.aiter_bytes():
            data.extend(chunk)
            if len(data) > MAX_PDF_BYTES:
                raise ValueError("PDF larger than 20 MB")
    import pdfplumber

    with pdfplumber.open(io.BytesIO(bytes(data))) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    await cache.set_json(f"pdftext:{url}", text, PDF_TTL)
    return text


def extract_values(text: str, url: str) -> dict[str, Cell]:
    out: dict[str, Cell] = {}
    if not text.strip():
        return out
    source = "Manufacturer spec sheet PDF: \"{quote}\""

    if not _THICKNESS_LIST.search(text):  # a family list of thicknesses → ambiguous
        found = {m.group(1): m.group(0) for m in _THICKNESS_LABELED.finditer(text)}
        found.update({m.group(1): m.group(0) for m in _THICKNESS_HEADING.finditer(text)})
        values = {float(v) for v in found}
        if len(values) == 1:
            raw, quote = next(iter(found.items()))
            value = f"{float(raw):g} mil"
            out["Thickness"] = Cell(value, "spec_sheet", "medium",
                                    source.format(quote=" ".join(quote.split())), url)

    standards: list[str] = []
    quotes: list[str] = []
    for m in _ASTM.finditer(text):
        std = f"ASTM D-{m.group(1)}"
        if std not in standards:
            standards.append(std)
            quotes.append(m.group(0))
    if standards:
        out["ASTM"] = Cell("|".join(standards), "spec_sheet", "medium",
                           source.format(quote="; ".join(quotes)), url)
    return out


async def read_spec_sheet(url: str, existing: dict[str, Cell], cache: Cache,
                          client: httpx.AsyncClient) -> SpecSheetResult:
    try:
        text = await fetch_text(url, cache, client)
    except Exception as e:
        return SpecSheetResult(url, False, f"spec sheet not read ({type(e).__name__}: {str(e)[:80]})")
    if not text.strip():
        return SpecSheetResult(url, False, "spec sheet has no readable text (scanned PDF?)")
    result = SpecSheetResult(url, True)
    for column, cell in extract_values(text, url).items():
        current = existing.get(column)
        if current is None:
            result.cells[column] = cell
        elif column == "Thickness" and current.value.replace(" ", "").lower() != cell.value.replace(" ", "").lower():
            result.conflicts.append(f"{column}: spec sheet says '{cell.value}', kept '{current.value}'")
    return result
