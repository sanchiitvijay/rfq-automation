"""Unit parsing for the four measured columns. Standard units: Length ft, Width in, Thickness mil, Weight lb."""
from __future__ import annotations

import re
from dataclasses import dataclass

STANDARD_UNIT = {"Length": "ft", "Width": "in", "Thickness": "mil", "Weight": "lb"}

_ALIASES = {
    "ft": "ft", "feet": "ft", "foot": "ft", "'": "ft",
    "yd": "yd", "yds": "yd", "yard": "yd", "yards": "yd",
    "in": "in", "inch": "in", "inches": "in", '"': "in",
    "m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "mm": "mm", "cm": "cm",
    "mil": "mil", "mils": "mil",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "oz": "oz", "kg": "kg", "g": "g",
}
# Multiply a value in <unit> by this to get the column's standard unit.
_TO_STANDARD = {
    "Length": {"ft": 1, "yd": 3, "in": 1 / 12, "m": 3.28084, "cm": 0.0328084, "mm": 0.00328084},
    "Width": {"in": 1, "ft": 12, "mm": 1 / 25.4, "cm": 1 / 2.54, "m": 39.3701},
    "Thickness": {"mil": 1, "in": 1000, "mm": 39.3701},
    "Weight": {"lb": 1, "oz": 1 / 16, "kg": 2.20462, "g": 0.00220462},
}
_VALUE = re.compile(r"^\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|\.\d+)\s*([A-Za-z]+\.?|['\"])?\s*$")


@dataclass
class Measure:
    number: float  # in the column's standard unit
    standard: str  # e.g. "1000 ft"
    is_standard: bool  # the cell is already written exactly like that
    note: str = ""  # why it is not standard


def fmt(number: float, converted: bool = False) -> str:
    """Converted values are snapped to whole numbers when within rounding error (333.33 yd → 1000 ft)."""
    value = round(number, 2)
    if converted and abs(value - round(value)) <= 0.011:
        value = round(value)
    return f"{value:g}"


def parse(column: str, value: str) -> Measure | None:
    """None when the value is not a single number with a known unit (e.g. '6 in x 300 ft')."""
    unit_std = STANDARD_UNIT[column]
    m = _VALUE.match(value)
    if not m:
        return None
    number = float(m.group(1).replace(",", ""))
    raw_unit = (m.group(2) or "").lower().rstrip(".")
    if not raw_unit:
        std = f"{fmt(number)} {unit_std}"
        return Measure(number, std, False, f"no unit given; {column} is in {unit_std} by convention")
    unit = _ALIASES.get(raw_unit)
    factor = _TO_STANDARD[column].get(unit or "")
    if factor is None:
        return None
    converted = number * factor
    std = f"{fmt(converted, converted=unit != unit_std)} {unit_std}"
    if value.strip() == std:
        return Measure(converted, std, True)
    if unit != unit_std:
        return Measure(converted, std, False, f"{value.strip()} = {std}")
    return Measure(converted, std, False, f"written differently from the standard form '{std}'")
