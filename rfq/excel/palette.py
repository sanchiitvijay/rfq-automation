"""One colour palette for every spreadsheet the app writes (.xlsx and .xls), matching the web app."""
from __future__ import annotations

# name: (fill RGB, text RGB or None, meaning shown in the legend)
COLOURS: dict[str, tuple[str, str | None, str]] = {
    "header": ("06307F", "FFFFFF", "column headers (RFQ template colour)"),
    "missing": ("D9D9D9", None, "missing: no source had a value"),
    "suspicious": ("F8CBAD", None, "check this value (reason in the cell comment)"),
    "manual": ("D3E9FD", None, "edited by hand in the app or via upload"),
    "not_found": ("FBE2D5", None, "product not found (whole row)"),
    "status_found": ("E7F3E8", "2E7D32", "Lookup Status: Found"),
    "status_manual": ("D3E9FD", "00446A", "Lookup Status: filled by hand"),
    "status_not_found": ("FDECEA", "B42318", "Lookup Status: Not found"),
    "conf_high": ("E7F3E8", "2E7D32", "source confidence: high"),
    "conf_medium": ("FFEDDA", "7A2E0B", "source confidence: medium"),
    "conf_low": ("FDECEA", "B42318", "source confidence: low"),
    "section": ("F0F3F5", None, "summary table headers"),
}

STATUS_COLOUR = {"Found": "status_found", "Manual": "status_manual", "Not found": "status_not_found"}
CONFIDENCE_COLOUR = {"high": "conf_high", "medium": "conf_medium", "low": "conf_low"}
LEGEND = ("missing", "suspicious", "manual", "not_found", "status_found", "status_manual", "status_not_found",
          "conf_high", "conf_medium", "conf_low")


def fill_of(name: str) -> str:
    return COLOURS[name][0]


def text_of(name: str) -> str | None:
    return COLOURS[name][1]
