"""Renders a Sheet (+ optional QualityReport) into the RFQ template.

The workbook is always generated from state, never edited in place, so the web editor and the file
cannot drift apart. External text is always written as a string cell: only our own =IMAGE() formula
is ever a formula (no formula injection from emails, web pages or PDFs).
"""
from __future__ import annotations

import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell as XlCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from rfq.config import (
    NOTES_COLUMNS, RFQ_COLUMNS, SOURCES_COLUMNS, STATUS_NOT_FOUND, SUPPLIER_COLUMNS, SUPPLIER_PREFIX, TEMPLATE_PATH,
)
from rfq.models import Cell, QualityReport, Sheet

GREY = PatternFill("solid", fgColor="D9D9D9")  # missing
ORANGE = PatternFill("solid", fgColor="F8CBAD")  # suspicious
NOT_FOUND = PatternFill("solid", fgColor="FBE2D5")
HEADER_FILL = PatternFill("solid", fgColor="06307F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SAFE_URL = re.compile(r"^https?://[^\s\"<>]+$")
LINK_FONT = Font(color="1379C8", underline="single")
LINK_COLUMNS = {"Product page", "Spec sheet"}


def column_letter(column: str) -> str:
    return get_column_letter(RFQ_COLUMNS.index(column) + 1)


def _put(cell: XlCell, value: str) -> None:
    """Writes external text as a plain string, never as a formula."""
    cell.value = value
    if isinstance(value, str) and value:
        cell.data_type = "s"


def _image_formula(url: str) -> str | None:
    return f'=IMAGE("{url}")' if SAFE_URL.match(url) else None


def _header(ws: Worksheet, columns: list[str]) -> None:
    for j, name in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=j, value=name)
        cell.font, cell.fill = HEADER_FONT, HEADER_FILL


def _fill_rfq(ws: Worksheet, sheet: Sheet) -> None:
    for i, row in enumerate(sheet.rows, start=2):
        for j, column in enumerate(RFQ_COLUMNS, start=1):
            target = ws.cell(row=i, column=j)
            if column == "product_id":
                _put(target, row.product_id)
            elif column == "Lookup Status":
                _put(target, row.lookup_status)
            elif column == "Image":
                url = row.value("Image")
                formula = _image_formula(url) if url else None
                if formula:
                    target.value = formula  # our own formula, URL validated above
                elif url:
                    _put(target, url)
            else:
                value = row.value(column)
                if value:
                    _put(target, value)
            target.alignment = Alignment(vertical="top", wrap_text=column == "Product details")


def _link(target: XlCell, url: str) -> None:
    """A clickable link, only for plain http(s) addresses."""
    if url and SAFE_URL.match(url):
        _put(target, url)
        target.hyperlink = url
        target.font = LINK_FONT


def _fill_sources(ws: Worksheet, sheet: Sheet) -> None:
    """One row per filled value: RFQ columns first, then the product's supplier values."""
    _header(ws, SOURCES_COLUMNS)
    r = 2

    def write(pid: str, column: str, cell: Cell) -> None:
        nonlocal r
        for j, value in enumerate([pid, column, cell.value, cell.source_type, cell.confidence, cell.source],
                                  start=1):
            _put(ws.cell(row=r, column=j), value)
        _link(ws.cell(row=r, column=7), cell.url)
        r += 1

    for row in sheet.rows:
        for column in RFQ_COLUMNS[1:-1]:
            cell = row.cells.get(column)
            if cell and cell.value:
                write(row.product_id, column, cell)
        for column in SUPPLIER_COLUMNS:
            cell = row.supplier.get(column)
            if cell and cell.value:
                write(row.product_id, SUPPLIER_PREFIX + column, cell)
    for col, width in {"A": 14, "B": 26, "C": 40, "D": 20, "E": 11, "F": 70, "G": 60}.items():
        ws.column_dimensions[col].width = width


def _fill_supplier(ws: Worksheet, sheet: Sheet) -> None:
    columns = ["product_id", *SUPPLIER_COLUMNS, "Lookup Status", "Found via"]
    _header(ws, columns)
    for i, row in enumerate(sheet.rows, start=2):
        for j, column in enumerate(columns, start=1):
            target = ws.cell(row=i, column=j)
            if column == "product_id":
                _put(target, row.product_id)
            elif column == "Lookup Status":
                _put(target, row.lookup_status)
            elif column == "Found via":
                _put(target, {"live": "ferguson.com page", "cache": "ferguson.com page (cached)",
                              "serpapi+catalog": "SerpApi + backup catalog", "serpapi": "SerpApi (Google)",
                              "catalog": "backup catalog", "manual": "entered by hand", "none": ""}
                     .get(row.lookup_source, row.lookup_source))
            else:
                cell = row.supplier.get(column)
                if not cell or not cell.value:
                    continue
                if column in LINK_COLUMNS:
                    _link(target, cell.value)
                else:
                    _put(target, cell.value)
        if row.lookup_status == STATUS_NOT_FOUND:
            for j in range(1, len(columns) + 1):
                ws.cell(row=i, column=j).fill = NOT_FOUND
    note_row = len(sheet.rows) + 3
    _put(ws.cell(row=note_row, column=1), "Where each value comes from (with a link) is on the Sources sheet, "
                                          f"under '{SUPPLIER_PREFIX}<column>'. Catalog prices date from 2026-09-24.")
    ws.freeze_panes = "B2"
    for col, width in {"A": 14, "B": 12, "C": 20, "D": 20, "E": 18, "F": 15, "G": 12, "H": 14, "I": 60,
                       "J": 60, "K": 13, "L": 24}.items():
        ws.column_dimensions[col].width = width


def _fill_notes(ws: Worksheet, sheet: Sheet) -> None:
    _header(ws, NOTES_COLUMNS)
    r = 2
    for warning in sheet.warnings:
        _put(ws.cell(row=r, column=1), "(all)")
        _put(ws.cell(row=r, column=2), warning)
        r += 1
    for note in sheet.notes:
        _put(ws.cell(row=r, column=1), note.product_id)
        _put(ws.cell(row=r, column=2), note.note)
        r += 1
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 110


def _highlight(ws: Worksheet, sheet: Sheet, report: QualityReport) -> None:
    row_of = {r.product_id: i for i, r in enumerate(sheet.rows, start=2)}
    for flag in report.flags:
        if flag.type == "not_found":
            i = row_of.get(flag.product_id)
            if i:
                for j in range(1, len(RFQ_COLUMNS) + 1):
                    ws.cell(row=i, column=j).fill = NOT_FOUND
            continue
        fill = GREY if flag.type == "missing" else ORANGE
        ws[flag.cell].fill = fill


def render(sheet: Sheet, path: Path, report: QualityReport | None = None, email_info: dict | None = None) -> Path:
    from rfq.quality.summary import write_summary  # summary depends on writer helpers

    wb = load_workbook(TEMPLATE_PATH)
    _fill_rfq(wb["RFQ"], sheet)
    _fill_sources(wb["Sources"], sheet)
    _fill_supplier(wb.create_sheet("Supplier", index=wb.sheetnames.index("RFQ") + 1), sheet)
    notes = wb["Notes"] if "Notes" in wb.sheetnames else wb.create_sheet("Notes")
    _fill_notes(notes, sheet)
    if report is not None:
        _highlight(wb["RFQ"], sheet, report)
        write_summary(wb, sheet, report, email_info or {})
    if "How to fill" in wb.sheetnames:  # keep the instructions sheet last
        wb.move_sheet("How to fill", offset=len(wb.sheetnames) - 1 - wb.sheetnames.index("How to fill"))
    ws = wb["RFQ"]
    ws.freeze_panes = "C2"
    for column, width in {"A": 14, "B": 42, "R": 60, "U": 14, "V": 30}.items():
        ws.column_dimensions[column].width = width
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)  # atomic: a reader never sees a half-written file
    return path
