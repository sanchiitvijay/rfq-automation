"""Reads an RFQ workbook that was downloaded, edited in Excel and uploaded again, and works out what changed.

Nothing is written here. The result is a preview: the changes, which of them are valid, which clash
with edits other people made since the download, and every problem with the file. The web app shows
it, the user picks what to apply, and the normal (validated, versioned) edit path applies it.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Any

from openpyxl import load_workbook

from rfq.config import RFQ_COLUMNS, SPEC_COLUMNS
from rfq.excel.exports import REVIEW_NOTES
from rfq.models import Sheet
from rfq.validation import EditError, validate

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
META_SHEET = "_rfq_meta"
# Excel 365 re-saves IMAGE() as _xlfn.IMAGE()
_IMAGE = re.compile(r'^=(?:_xlfn\.)?IMAGE\("(https?://[^"]+)"', re.IGNORECASE)
IGNORED_COLUMNS = {"product_id", "Lookup Status"}


@dataclass
class Change:
    product_id: str
    column: str
    current: str
    uploaded: str
    base: str | None  # value in the version the file was downloaded from (None if unknown)
    status: str  # "ok" | "invalid" | "conflict"
    message: str = ""
    cell: str = ""  # cell on the uploaded RFQ sheet, e.g. "S4"


@dataclass
class ImportPreview:
    ok: bool
    filename: str
    file_job_id: str = ""
    file_version: int | None = None
    current_version: int = 0
    changes: list[Change] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # file-level: nothing can be applied
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["counts"] = {s: sum(1 for c in self.changes if c.status == s) for s in ("ok", "invalid", "conflict")}
        return out


def _text(value: Any) -> str:
    """Excel turns some typed values into numbers or dates; bring them back to the text we store."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _letter(index: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(index + 1)


@dataclass
class _Cell:
    """One cell of any uploaded format: value, its A1 reference and its row number."""

    value: Any
    coordinate: str
    row: int


def _grid(values: list[list[Any]]) -> list[list[_Cell]]:
    return [[_Cell(v, f"{_letter(j)}{i}", i) for j, v in enumerate(r)] for i, r in enumerate(values, start=1)]


def _decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):  # Excel on Windows saves CSV as cp1252 unless told otherwise
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _uncsv(text: str) -> str:
    """Undo the CSV-injection guard of our own export: '=x → =x is NOT restored (formulas stay text)."""
    return text[1:] if text[:1] == "'" and text[1:2] in ("=", "+", "-", "@") else text


def load_table(data: bytes, filename: str, result: ImportPreview) -> tuple[dict[str, str], list[list[_Cell]]] | None:
    """The RFQ sheet of an .xlsx/.xlsm/.xls/.csv upload, plus the RFQ Agent version stamp if the file has one.
    Problems are added to result.errors and None is returned."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        try:
            wb = load_workbook(io.BytesIO(data), data_only=False)  # formulas visible, so they can be refused
        except (zipfile.BadZipFile, KeyError, OSError, ValueError) as e:
            result.errors.append(f"The file could not be opened as an Excel workbook ({type(e).__name__}); "
                                 "it may be corrupt or password protected.")
            return None
        if "RFQ" not in wb.sheetnames:
            result.errors.append("The workbook has no sheet called 'RFQ'. Keep the sheet names as downloaded.")
            return None
        rows = [[_Cell(c.value, c.coordinate, c.row) for c in r] for r in wb["RFQ"].iter_rows()]
        return read_meta(wb), rows
    if name.endswith(".xls"):
        import xlrd

        try:
            book = xlrd.open_workbook(file_contents=data)
        except Exception as e:  # xlrd raises its own error types for encrypted / corrupt / not-really-xls files
            result.errors.append(f"The file could not be opened as an Excel 97–2003 workbook ({type(e).__name__}); "
                                 "it may be corrupt, password protected or not really an .xls file.")
            return None
        if "RFQ" not in book.sheet_names():
            result.errors.append("The workbook has no sheet called 'RFQ'. Keep the sheet names as downloaded.")
            return None
        sheet = book.sheet_by_name("RFQ")
        meta: dict[str, str] = {}
        if META_SHEET in book.sheet_names():
            m = book.sheet_by_name(META_SHEET)
            meta = {_text(m.cell_value(i, 0)): _text(m.cell_value(i, 1)) for i in range(m.nrows) if m.ncols >= 2}
        values = [[None if v == "" else v for v in sheet.row_values(i)] for i in range(sheet.nrows)]
        return meta, _grid(values)
    if name.endswith(".csv"):
        import csv

        text = _decode_csv(data)
        if "\x00" in text:
            result.errors.append("This does not look like a CSV text file.")
            return None
        try:
            dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel  # one column or unusual file: plain commas
        try:
            values = [[_uncsv(v) if v != "" else None for v in r] for r in csv.reader(io.StringIO(text), dialect)]
        except csv.Error as e:
            result.errors.append(f"The CSV file could not be read ({e}).")
            return None
        return {}, _grid([r for r in values if any(v is not None for v in r)])
    result.errors.append("Upload the RFQ as .xlsx, .xlsm, .xls or .csv. Other formats are not read.")
    return None


def read_meta(wb: Any) -> dict[str, str]:
    if META_SHEET not in wb.sheetnames:
        return {}
    return {_text(k): _text(v) for k, v, *_ in wb[META_SHEET].iter_rows(max_col=2, values_only=True) if k}


def preview(data: bytes, filename: str, job_id: str, current: Sheet, current_version: int,
            base: Sheet | None = None) -> ImportPreview:
    """`base` is the sheet at the version written in the file (when we still have it)."""
    result = ImportPreview(ok=False, filename=filename, current_version=current_version)
    if len(data) > MAX_UPLOAD_BYTES:
        result.errors.append("The file is larger than 10 MB.")
        return result
    loaded = load_table(data, filename, result)
    if loaded is None:
        return result
    meta, rows = loaded

    result.file_job_id = meta.get("job_id", "")
    if meta.get("version", "").isdigit():
        result.file_version = int(meta["version"])
    if result.file_job_id and result.file_job_id != job_id:
        result.errors.append("This workbook belongs to a different RFQ request. Open the right request and "
                             "upload it there.")
        return result
    if not meta:
        result.warnings.append("The file has no RFQ Agent version stamp (CSV files never have one, and a re-saved "
                               "workbook may lose it), so it is compared with the current version only.")
    elif result.file_version is not None and result.file_version < current_version:
        result.warnings.append(f"This file was downloaded at version {result.file_version}; the RFQ is now at "
                               f"version {current_version}. Cells changed by others since then are marked as "
                               "conflicts and are not applied unless you tick them.")
    if not rows:
        result.errors.append("The RFQ sheet is empty.")
        return result
    header = [_text(c.value) for c in rows[0]]
    missing = [c for c in RFQ_COLUMNS if c not in header]
    if missing:
        result.errors.append(f"The RFQ sheet is missing these columns: {', '.join(missing)}. Do not rename or "
                             "delete header cells.")
        return result
    extra = [h for h in header if h and h not in RFQ_COLUMNS and h != REVIEW_NOTES]  # our own CSV column
    if extra:
        result.warnings.append(f"Extra columns are ignored: {', '.join(extra)}.")
    col_index = {name: header.index(name) for name in RFQ_COLUMNS}

    current_rows = {r.product_id: r for r in current.rows}
    base_rows = {r.product_id: r for r in base.rows} if base else {}
    seen: set[str] = set()
    for excel_row in rows[1:]:
        pid = _text(excel_row[col_index["product_id"]].value)
        if not pid:
            if any(_text(c.value) for c in excel_row):
                result.warnings.append(f"Row {excel_row[0].row} has no product_id and is ignored.")
            continue
        if pid in seen:
            result.errors.append(f"Product {pid} appears more than once on the RFQ sheet (row {excel_row[0].row}).")
            continue
        seen.add(pid)
        row = current_rows.get(pid)
        if row is None:
            result.warnings.append(f"Row {excel_row[0].row}: product {pid} is not in this RFQ and is ignored "
                                   "(new products cannot be added by upload).")
            continue
        base_row = base_rows.get(pid)
        for column in SPEC_COLUMNS:
            if column == "Image":
                continue  # Image follows Picture; only the Picture address is read
            cell = excel_row[col_index[column]] if col_index[column] < len(excel_row) else None
            raw = cell.value if cell is not None else None
            ref = cell.coordinate if cell is not None else f"{_letter(col_index[column])}{excel_row[0].row}"
            if isinstance(raw, str) and raw.startswith("="):
                m = _IMAGE.match(raw)
                if column in ("Image", "Picture") and m:
                    raw = m.group(1)
                else:
                    result.changes.append(Change(pid, column, row.value(column), raw, None, "invalid",
                                                     "formulas are not allowed; type the value itself", ref))
                    continue
            uploaded = _text(raw)
            now = row.value(column)
            before = base_row.value(column) if base_row else None
            reference = before if before is not None else now
            if uploaded == reference or uploaded == now:
                continue  # not changed in the file (or already applied)
            change = Change(pid, column, now, uploaded, before, "ok", cell=ref)
            try:
                cleaned = validate(column, uploaded)
                change.uploaded = cleaned
            except EditError as e:
                change.status, change.message = "invalid", str(e)
            if change.status == "ok" and before is not None and now != before:
                change.status = "conflict"
                change.message = (f"changed in the app since your download (was '{before or 'blank'}', "
                                  f"now '{now or 'blank'}')")
            if change.status == "ok" and not uploaded and now:
                change.message = "clears this value"
            result.changes.append(change)

    not_in_file = [pid for pid in current_rows if pid not in seen]
    if not_in_file:
        result.warnings.append(f"Not in the uploaded file, kept unchanged: {', '.join(not_in_file)} (to remove a "
                               "product, use 'Remove selected row' in the app, which asks for a reason).")
    result.warnings.append("Only the RFQ sheet is read (and in it, the Picture address rather than the Image "
                           "cell, which follows Picture). The Supplier, Sources, Summary and Notes sheets are "
                           "rebuilt by the app.")
    result.ok = not result.errors
    return result
