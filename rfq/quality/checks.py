"""Code-based quality checks. They only ever flag; no cell value is changed."""
from __future__ import annotations

import re

from rfq.config import SPEC_COLUMNS, STATUS_NOT_FOUND
from rfq.excel.writer import column_letter
from rfq.models import Flag, Row, Sheet
from rfq.quality import units

RANGES = {  # plausible range in the standard unit for this product range (tapes)
    "Width": (0.25, 24), "Length": (10, 5000), "Thickness": (1, 20), "Weight": (0.05, 200),
}
UTILITIES = {
    "water": ("water", "potable"),
    "sewer": ("sewer", "drain", "storm"),
    "gas": ("gas", "oil", "steam", "petroleum"),
    "electric": ("electric", "power"),
    "communication": ("telephone", "telecom", "communication", "fiber", "fibre", "cable", "catv"),
    "reclaimed": ("reclaimed", "irrigation", "slurry"),
}
APWA = {"blue": "water", "green": "sewer", "yellow": "gas", "red": "electric", "orange": "communication",
        "purple": "reclaimed"}
COLORS = ("blue", "green", "yellow", "red", "orange", "purple", "white", "pink", "black", "brown", "silver")
_DESC_DIMS = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:in\.?|inch(?:es)?|\")\s*x\s*(\d[\d,]*(?:\.\d+)?)\s*(?:ft\.?|feet|')", re.IGNORECASE)
_DESC_MIL = re.compile(r"(\d+(?:\.\d+)?)\s*mil\b", re.IGNORECASE)
_URL = re.compile(r"^https?://\S+$")


def _flag(flags: list[Flag], row_no: int, row: Row, column: str, type_: str, reason: str) -> None:
    flags.append(Flag(f"{column_letter(column)}{row_no}", row.product_id, column, type_, "code", reason))  # type: ignore[arg-type]


def _utilities(text: str) -> set[str]:
    words = text.lower()
    return {u for u, keys in UTILITIES.items() if any(re.search(rf"\b{k}", words) for k in keys)}


def _lettering_utility(lettering: str) -> str | None:
    m = re.search(r"buried\s+(.+?)\s+line", lettering, re.IGNORECASE)
    found = _utilities(m.group(1) if m else lettering)
    return next(iter(found)) if len(found) == 1 else None


def _check_units(flags: list[Flag], n: int, row: Row) -> dict[str, float]:
    numbers: dict[str, float] = {}
    for column in units.STANDARD_UNIT:
        value = row.value(column)
        if not value:
            continue
        measure = units.parse(column, value)
        if measure is None:
            _flag(flags, n, row, column, "suspicious", f"'{value}' is not a single {column.lower()} with a known unit")
            continue
        numbers[column] = measure.number
        if not measure.is_standard:
            _flag(flags, n, row, column, "suspicious", f"non-standard unit: {measure.note} (standard: {measure.standard})")
        low, high = RANGES[column]
        if not low <= measure.number <= high:
            _flag(flags, n, row, column, "suspicious",
                  f"{measure.standard} is outside the usual {low:g}–{high:g} {units.STANDARD_UNIT[column]} for these products")
    return numbers


def _check_description(flags: list[Flag], n: int, row: Row, numbers: dict[str, float]) -> None:
    desc = row.value("Description")
    if not desc:
        return
    m = _DESC_DIMS.search(desc)
    if m:
        width, length = float(m.group(1)), float(m.group(2).replace(",", ""))
        if "Width" in numbers and abs(numbers["Width"] - width) > 0.01:
            _flag(flags, n, row, "Width", "suspicious",
                  f"Description says {width:g} in wide but Width is {row.value('Width')}")
        if "Length" in numbers and abs(numbers["Length"] - length) > 0.5:
            _flag(flags, n, row, "Length", "suspicious",
                  f"Description says {length:g} ft long but Length is {row.value('Length')}")
    mil = _DESC_MIL.search(desc)
    if mil and "Thickness" in numbers and abs(numbers["Thickness"] - float(mil.group(1))) > 0.01:
        _flag(flags, n, row, "Thickness", "suspicious",
              f"Description says {mil.group(1)} mil but Thickness is {row.value('Thickness')}")
    color = row.value("Color Finish").lower()
    named = [c for c in COLORS if re.search(rf"\b{c}\b", desc.lower())]
    if color and named and not any(c in color for c in named):
        _flag(flags, n, row, "Color Finish", "suspicious",
              f"Description mentions {', '.join(named)} but Color Finish is {row.value('Color Finish')}")


def _check_utility(flags: list[Flag], n: int, row: Row) -> None:
    lettering = row.value("Lettering")
    utility = _lettering_utility(lettering) if lettering else None
    if not utility:
        return
    color = row.value("Color Finish").lower()
    expected = APWA.get(color)
    if expected and expected != utility:
        _flag(flags, n, row, "Color Finish", "suspicious",
              f"lettering marks a {utility} line, but APWA {row.value('Color Finish')} means {expected}")
    application = _utilities(row.value("Application"))
    if application and utility not in application:
        listed = ", ".join(sorted(application))
        _flag(flags, n, row, "Application", "suspicious",
              f"Application lists {listed} but the lettering ('{lettering}') marks a {utility} line")


def _check_misc(flags: list[Flag], n: int, row: Row) -> None:
    image, picture = row.value("Image"), row.value("Picture")
    for column, url in (("Image", image), ("Picture", picture)):
        if url and not all(_URL.match(u.strip()) for u in url.split("|")):
            _flag(flags, n, row, column, "suspicious", f"'{url[:60]}' is not a web address")
    if image and picture and image != picture:
        _flag(flags, n, row, "Picture", "suspicious", "Picture URL differs from the URL in the Image formula")
    tools = row.value("No of Tools")
    if tools and not re.fullmatch(r"[1-9]\d{0,3}", tools):
        _flag(flags, n, row, "No of Tools", "suspicious", f"'{tools}' is not a whole number of tools")
    ul = row.value("UL Listed")
    if ul and ul not in ("Yes", "No"):
        _flag(flags, n, row, "UL Listed", "suspicious", f"'{ul}' should be Yes or No")


def run_code_checks(sheet: Sheet) -> list[Flag]:
    flags: list[Flag] = []
    for n, row in enumerate(sheet.rows, start=2):
        if row.lookup_status == STATUS_NOT_FOUND:
            reason = row.not_found_reason or "product not found in any source"
            flags.append(Flag(f"A{n}", row.product_id, "product_id", "not_found", "code", reason))
            continue
        for column in SPEC_COLUMNS:
            if not row.value(column):
                _flag(flags, n, row, column, "missing", "missing: no source had this value")
        numbers = _check_units(flags, n, row)
        _check_description(flags, n, row, numbers)
        _check_utility(flags, n, row)
        _check_misc(flags, n, row)
    return flags
