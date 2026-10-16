"""The backup catalog (collected from ferguson.com on 2026-09-24) and the source of every value in it."""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache

from rfq.config import CATALOG_JSON, CATALOG_SOURCES_CSV, SPEC_COLUMNS, SPEC_LINKS_CSV
from rfq.models import Cell

CATALOG_SOURCE = "Backup product catalog (data/product_catalog.json), collected from ferguson.com on 2026-09-24"
# Catalog column that feeds an RFQ column when the names differ.
CATALOG_COLUMN_FOR = {"Image": "Picture URL", "Picture": "Picture URL"}
EMPTY_MARKERS = {"", "[]", "n/a", "N/A", "none", "None", "-"}


def clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text in EMPTY_MARKERS else text


@lru_cache(maxsize=1)
def _catalog() -> dict[str, dict[str, str]]:
    return json.loads(CATALOG_JSON.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _sources() -> dict[tuple[str, str], dict[str, str]]:
    with CATALOG_SOURCES_CSV.open(encoding="utf-8-sig", newline="") as f:
        return {(r["product_id"], r["column"]): r for r in csv.DictReader(f)}


@lru_cache(maxsize=1)
def spec_sheet_links() -> dict[str, str]:
    with SPEC_LINKS_CSV.open(encoding="utf-8-sig", newline="") as f:
        return {r["product_id"]: r["spec_sheet_url"] for r in csv.DictReader(f) if r.get("spec_sheet_url")}


def has(product_id: str) -> bool:
    return product_id in _catalog()


def raw(product_id: str) -> dict[str, str] | None:
    return _catalog().get(product_id)


# Source types whose value was read from the product's own Ferguson page (so that page is the link).
PAGE_SOURCE_TYPES = {"ferguson_rfq_sample", "ferguson_page", "same_product_description"}
SUPPLIER_FROM_CATALOG = {"Brand": "Brand", "Manufacturer Part #": "Manufacturer Part #",
                         "Ferguson Part #": "Ferguson Part #", "UPC": "UPC", "Price (USD)": "Price (USD)",
                         "Availability": "Availability"}


_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)]+")


def _link(record: dict[str, str], product_id: str, source_type: str, source_text: str = "") -> str:
    """The page or PDF a catalog value came from; "" for rule-based values (no single document).
    A URL named in the source text wins: it is exactly the document the value was taken from
    (for example a sibling product's family spec sheet)."""
    named = _URL_IN_TEXT.search(source_text or "")
    if named:
        return named.group(0).rstrip(".,;")
    if source_type in PAGE_SOURCE_TYPES:
        return clean(record.get("Ferguson URL"))
    if source_type == "spec_sheet":
        return clean(record.get("Spec Sheet URL")) or spec_sheet_links().get(product_id, "")
    return ""


def _cell(record: dict[str, str], product_id: str, key: str, value: str) -> Cell:
    src = _sources().get((product_id, key))
    if src:
        return Cell(value, src["source_type"], src["confidence"], src["source"],
                    _link(record, product_id, src["source_type"], src["source"]))
    # value present but the sources file has no row for it (e.g. Description): it came from the product page
    url = clean(record.get("Ferguson URL"))
    return Cell(value, "ferguson_page", "high", f"{CATALOG_SOURCE}; product page", url)


def cells(product_id: str) -> dict[str, Cell]:
    """Every non-blank RFQ value for a product, each with the source (and link) recorded for it."""
    record = _catalog().get(product_id)
    if record is None:
        return {}
    out: dict[str, Cell] = {}
    for column in SPEC_COLUMNS:
        key = CATALOG_COLUMN_FOR.get(column, column)
        value = clean(record.get(key))
        if value:
            out[column] = _cell(record, product_id, key, value)
    return out  # Image holds the picture URL; the Excel writer turns it into =IMAGE("…")


def supplier(product_id: str) -> dict[str, Cell]:
    """Supplier sheet values from the catalog (price and stock are as of the collection date)."""
    record = _catalog().get(product_id)
    if record is None:
        return {}
    url = clean(record.get("Ferguson URL"))
    out: dict[str, Cell] = {
        "Supplier": Cell("Ferguson", "ferguson_page", "high",
                         f"{CATALOG_SOURCE}; listed on ferguson.com at the time", url),
    }
    for column, key in SUPPLIER_FROM_CATALOG.items():
        value = clean(record.get(key))
        if value:
            cell = _cell(record, product_id, key, value)
            if column in ("Price (USD)", "Availability"):
                cell.source += " (may have changed since)"
            out[column] = cell
    if url:
        out["Product page"] = Cell(url, "ferguson_page", "high", CATALOG_SOURCE, url)
    spec = clean(record.get("Spec Sheet URL")) or spec_sheet_links().get(product_id, "")
    if spec:
        out["Spec sheet"] = Cell(spec, "spec_sheet", "high", "data/spec_sheet_links.csv", spec)
    return out


def column_values(column: str) -> list[str]:
    """Every distinct value the catalog holds for an RFQ column (for the editor's dropdown suggestions)."""
    key = CATALOG_COLUMN_FOR.get(column, column)
    return [v for v in (clean(r.get(key)) for r in _catalog().values()) if v]
