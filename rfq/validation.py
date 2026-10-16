"""Validation for values typed in by the sourcing team (human-in-the-loop edits)."""
from __future__ import annotations

import re

from rfq.config import SPEC_COLUMNS
from rfq.quality import units

MAX_LEN = 2000
_URL = re.compile(r"^https?://[^\s\"<>|]+$")
PIPE_LIST_COLUMNS = {"Application", "ASTM", "Material", "Waterworks Application", "Product details"}
READ_ONLY = {"product_id", "Lookup Status"}
CHOICES = {"UL Listed": ("Yes", "No")}  # the only values these columns accept
FREE_TEXT = {"Description", "Product details", "Image", "Picture"}  # no dropdown: each value is unique
MAX_SUGGESTIONS = 40


class EditError(ValueError):
    pass


def validate(column: str, value: str) -> str:
    """Returns the cleaned value or raises EditError with a message for the user. '' clears the cell."""
    if column in READ_ONLY:
        raise EditError(f"{column} cannot be edited")
    if column == "Image":
        raise EditError("Image follows Picture: change the Picture address and the image updates with it")
    if column not in SPEC_COLUMNS:
        raise EditError(f"unknown column '{column}'")
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) > MAX_LEN:
        raise EditError(f"too long (max {MAX_LEN} characters)")
    if value[0] in "=+@" or value.startswith("-="):
        raise EditError("values may not start with = + or @ (spreadsheet formulas are not allowed)")
    if any(ord(ch) < 32 and ch not in "\t" for ch in value):
        raise EditError("line breaks and control characters are not allowed; separate list items with |")
    if column in units.STANDARD_UNIT:
        measure = units.parse(column, value)
        unit = units.STANDARD_UNIT[column]
        if measure is None or measure.note.startswith("no unit"):
            raise EditError(f"enter a number with a unit, e.g. '12 {unit}'")
        return value
    if column in ("Image", "Picture"):
        parts = [p.strip() for p in value.split("|")]
        if not parts or any(not _URL.match(p) for p in parts):
            raise EditError("enter a full web address starting with https:// (several can be separated by |)")
        return "|".join(parts)
    if column == "No of Tools" and not re.fullmatch(r"[1-9]\d{0,3}", value):
        raise EditError("enter a whole number, e.g. 1")
    if column in CHOICES and value not in CHOICES[column]:
        raise EditError(f"choose {' or '.join(CHOICES[column])}")
    if column in PIPE_LIST_COLUMNS:
        parts = [p.strip() for p in value.split("|")]
        if any(not p for p in parts):
            raise EditError("empty item in the list; separate items with a single |")
        return "|".join(parts)
    return value


def column_options(seen: dict[str, list[str]]) -> dict[str, dict[str, list[str]]]:
    """Dropdown options per editable column, for the review grid.

    `choices` are the only accepted values; `suggestions` are values already used (in this RFQ or the catalog),
    most common first, and only ones that would pass validation, so picking one can never be rejected.
    Typing a new value stays possible for suggestion columns.
    """
    out: dict[str, dict[str, list[str]]] = {}
    for column in SPEC_COLUMNS:
        if column in READ_ONLY or column in FREE_TEXT:
            continue
        if column in CHOICES:
            out[column] = {"choices": list(CHOICES[column])}
            continue
        counts: dict[str, int] = {}
        for raw in seen.get(column, []):
            try:
                value = validate(column, raw)
            except EditError:
                continue
            if not value:
                continue
            # list columns also offer each single item ("Water", "Gas"), so a new combination is easy to build
            items = value.split("|") if column in PIPE_LIST_COLUMNS and "|" in value else []
            for v in [value, *items]:
                counts[v] = counts.get(v, 0) + 1
        ranked = sorted(counts, key=lambda v: (-counts[v], v.lower()))
        out[column] = {"suggestions": ranked[:MAX_SUGGESTIONS]}
    return out
