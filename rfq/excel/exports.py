"""Download formats for the RFQ and the Summary: .xlsx (everything), .xls (Excel 97–2003) and .csv.

The .xlsx written by writer.py is the master copy; .xls is converted from it (same values, same colours),
and .csv is plain values only. The list of formats is served to the web app, so nothing is hardcoded there.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Any

from openpyxl import load_workbook

from rfq.config import RFQ_COLUMNS
from rfq.excel.images import primary_picture
from rfq.models import QualityReport, Sheet


@dataclass(frozen=True)
class Format:
    value: str
    label: str
    description: str
    extension: str
    media_type: str


FORMATS: dict[str, Format] = {
    "xlsx": Format("xlsx", "Excel workbook (.xlsx)", "All sheets with colours, pictures, links and comments",
                   ".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "xls": Format("xls", "Excel 97–2003 (.xls)", "All sheets with colours; no pictures, links or comments",
                  ".xls", "application/vnd.ms-excel"),
    "csv": Format("csv", "CSV (.csv)", "One sheet as plain values (no colours); flags in a 'Review notes' column",
                  ".csv", "text/csv; charset=utf-8"),
}
UPLOAD_EXTENSIONS = (".xlsx", ".xlsm", ".xls", ".csv")
REVIEW_NOTES = "Review notes"  # extra CSV column; ignored again on upload
XLS_MAX_TEXT = 32767
XLS_MAX_ROWS = 65536
_IMAGE = re.compile(r'^=(?:_xlfn\.)?IMAGE\("([^"]+)"', re.IGNORECASE)


class ExportError(ValueError):
    pass


# ---------------------------------------------------------------- CSV ----------------------------------------------
def _csv_safe(value: Any) -> str:
    """Spreadsheet apps run cells that start with = + @ as formulas (CSV injection): prefix them with '."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "@") or (text[:1] == "-" and text[1:2] and not (text[1].isdigit() or text[1] in " .")):
        return "'" + text
    return text


def _csv_bytes(rows: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    for row in rows:
        writer.writerow([_csv_safe(v) for v in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM: Excel then reads UTF-8 correctly


def rfq_csv(sheet: Sheet, report: QualityReport | None) -> bytes:
    flags: dict[str, list[str]] = {}
    for f in (report.flags if report else []):
        label = {"missing": "missing", "suspicious": "check", "not_found": "not found"}[f.type]
        flags.setdefault(f.product_id, []).append(f"{f.column}: {label}" if f.type != "not_found" else f"not found: {f.reason}")
    rows: list[list[Any]] = [[*RFQ_COLUMNS, REVIEW_NOTES]]
    for r in sheet.rows:
        line: list[Any] = []
        for column in RFQ_COLUMNS:
            if column == "product_id":
                line.append(r.product_id)
            elif column == "Lookup Status":
                line.append(r.lookup_status)
            elif column == "Image":
                line.append(primary_picture(r.value("Image")) or r.value("Image"))  # CSV has no pictures: the URL
            else:
                line.append(r.value(column))
        line.append("; ".join(flags.get(r.product_id, [])))
        rows.append(line)
    return _csv_bytes(rows)


def sheet_csv(xlsx: bytes, sheet_name: str) -> bytes:
    ws = load_workbook(io.BytesIO(xlsx), data_only=False)[sheet_name]
    return _csv_bytes([["" if v is None else v for v in row] for row in ws.iter_rows(values_only=True)])


# ---------------------------------------------------------------- XLS ----------------------------------------------
def xlsx_to_xls(xlsx: bytes) -> bytes:
    """Same sheets, values, fills, bold/coloured text and column widths, in the Excel 97–2003 format."""
    import xlwt

    src = load_workbook(io.BytesIO(xlsx), data_only=False)
    out = xlwt.Workbook(encoding="utf-8")
    palette: dict[str, int] = {}
    styles: dict[tuple[str | None, str | None, bool], Any] = {}
    next_index = [0x21]  # custom colour slots 0x21–0x3F

    def colour(rgb: str | None) -> int | None:
        if not rgb or len(rgb) < 6:
            return None
        rgb = rgb[-6:].upper()
        if rgb not in palette:
            if next_index[0] > 0x3F:
                return None  # palette full: keep the cell readable without colour
            name = f"rfq_{rgb.lower()}"
            xlwt.add_palette_colour(name, next_index[0])
            out.set_colour_RGB(next_index[0], int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16))
            palette[rgb] = next_index[0]
            next_index[0] += 1
        return palette[rgb]

    def style(fill: str | None, font: str | None, bold: bool) -> Any:
        key = (fill, font, bold)
        if key not in styles:
            st = xlwt.XFStyle()
            if fill and (idx := colour(fill)) is not None:
                pat = xlwt.Pattern()
                pat.pattern = xlwt.Pattern.SOLID_PATTERN
                pat.pattern_fore_colour = idx
                st.pattern = pat
            fnt = xlwt.Font()
            fnt.bold = bold
            if font and font[-6:].upper() not in ("000000",) and (idx := colour(font)) is not None:
                fnt.colour_index = idx
            st.font = fnt
            st.alignment.wrap = xlwt.Alignment.NOT_WRAP_AT_RIGHT
            st.alignment.vert = xlwt.Alignment.VERT_TOP
            styles[key] = st
        return styles[key]

    for ws in src.worksheets:
        if ws.max_row > XLS_MAX_ROWS:
            raise ExportError(f"sheet '{ws.title}' has more than {XLS_MAX_ROWS} rows; use .xlsx")
        target = out.add_sheet(ws.title[:31], cell_overwrite_ok=True)
        if ws.sheet_state != "visible":
            target.visibility = 1
        for letter, dim in ws.column_dimensions.items():
            if dim.width:
                from openpyxl.utils import column_index_from_string

                target.col(column_index_from_string(letter) - 1).width = int(min(dim.width, 250) * 256)
        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                fill = cell.fill.fgColor.rgb if cell.fill and cell.fill.fill_type == "solid" else None
                font = cell.font.color.rgb if cell.font and cell.font.color is not None and isinstance(cell.font.color.rgb, str) else None
                if value is None and not fill:
                    continue
                if isinstance(value, str) and value.startswith("="):
                    m = _IMAGE.match(value)
                    value = m.group(1) if m else value[1:]  # .xls has no IMAGE(); never write a live formula
                if isinstance(value, str) and len(value) > XLS_MAX_TEXT:
                    value = value[: XLS_MAX_TEXT - 20] + " … (cut for .xls)"
                if isinstance(value, str) and font and font[-6:].upper() == "FFFFFF" and not fill:
                    font = None  # hidden-under-picture text (Image cells) has no picture to hide behind here
                target.write(cell.row - 1, cell.column - 1, value if value is not None else "",
                             style(fill, font, bool(cell.font and cell.font.b)))
        if ws.freeze_panes:
            target.set_panes_frozen(True)
            target.set_horz_split_pos(ws[ws.freeze_panes].row - 1)
            target.set_vert_split_pos(ws[ws.freeze_panes].column - 1)
    buf = io.BytesIO()
    out.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- entry point --------------------------------------
def export(what: str, fmt: str, *, rfq_xlsx: bytes, summary_xlsx: bytes, sheet: Sheet,
           report: QualityReport | None) -> tuple[bytes, Format]:
    """what = 'rfq' | 'summary'. Returns (file bytes, format)."""
    if fmt not in FORMATS:
        raise ExportError(f"unknown format '{fmt}' (choose {', '.join(FORMATS)})")
    if what not in ("rfq", "summary"):
        raise ExportError("choose what to download: rfq or summary")
    f = FORMATS[fmt]
    source = rfq_xlsx if what == "rfq" else summary_xlsx
    if fmt == "xlsx":
        return source, f
    if fmt == "xls":
        return xlsx_to_xls(source), f
    return (rfq_csv(sheet, report) if what == "rfq" else sheet_csv(summary_xlsx, "Summary")), f
