"""Validation for values typed in by the sourcing team (human-in-the-loop edits)."""
from __future__ import annotations

import re

from rfq.config import SPEC_COLUMNS
from rfq.quality import units

MAX_LEN = 2000
_URL = re.compile(r"^https?://[^\s\"<>|]+$")
PIPE_LIST_COLUMNS = {"Application", "ASTM", "Material", "Waterworks Application", "Product details"}
READ_ONLY = {"product_id", "Lookup Status"}


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
    if column == "UL Listed" and value not in ("Yes", "No"):
        raise EditError("enter Yes or No")
    if column in PIPE_LIST_COLUMNS:
        parts = [p.strip() for p in value.split("|")]
        if any(not p for p in parts):
            raise EditError("empty item in the list; separate items with a single |")
        return "|".join(parts)
    return value
