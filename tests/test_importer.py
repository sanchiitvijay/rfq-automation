"""Upload of an edited RFQ workbook: validated, three-way compared, never applied blindly."""
from __future__ import annotations

import io

import openpyxl
from helpers import eml, run_sync

from rfq.excel.importer import preview
from rfq.excel.writer import render


def _download(tmp_path, version="1", job_id="job-1"):
    result = run_sync(tmp_path / "run", eml("email-1"))
    path = render(result.sheet, tmp_path / "RFQ_v1.xlsx", result.report, meta={"job_id": job_id, "version": version},
                  embed_images=False)
    return result.sheet, path


def _edit(path, edits: dict[tuple[str, str], object], drop_meta=False, rename=None) -> bytes:
    wb = openpyxl.load_workbook(path)
    ws = wb["RFQ"]
    header = [c.value for c in ws[1]]
    for (pid, column), value in edits.items():
        for row in ws.iter_rows(min_row=2):
            if str(row[0].value) == pid:
                row[header.index(column)].value = value
    if drop_meta:
        del wb["_rfq_meta"]
    if rename:
        ws.cell(row=1, column=header.index(rename[0]) + 1, value=rename[1])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_opens_on_rfq_sheet(tmp_path):
    _, path = _download(tmp_path)
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames[0] == "RFQ" and wb.active.title == "RFQ"
    assert wb["_rfq_meta"].sheet_state == "hidden"


def test_unchanged_file_has_no_changes(tmp_path):
    sheet, path = _download(tmp_path)
    p = preview(path.read_bytes(), "RFQ.xlsx", "job-1", sheet, 1)
    assert p.ok and p.changes == [] and not p.errors


def test_valid_edits_and_invalid_ones(tmp_path):
    sheet, path = _download(tmp_path)
    data = _edit(path, {("5106880", "ANSI"): "ANSI Z535.1", ("5106880", "Weight"): "heavy",
                        ("5106912", "No of Tools"): 2, ("5106935", "Thickness"): "=1+1"})
    p = preview(data, "RFQ.xlsx", "job-1", sheet, 1)
    by = {(c.product_id, c.column): c for c in p.changes}
    assert by[("5106880", "ANSI")].status == "ok" and by[("5106880", "ANSI")].uploaded == "ANSI Z535.1"
    assert by[("5106880", "Weight")].status == "invalid" and "unit" in by[("5106880", "Weight")].message
    assert by[("5106912", "No of Tools")].status == "ok" and by[("5106912", "No of Tools")].uploaded == "2"
    assert by[("5106935", "Thickness")].status == "invalid" and "formulas" in by[("5106935", "Thickness")].message
    assert p.to_dict()["counts"] == {"ok": 2, "invalid": 2, "conflict": 0}


def test_image_formula_from_excel_365_is_not_a_change(tmp_path):
    sheet, path = _download(tmp_path)
    url = sheet.rows[0].value("Image")
    data = _edit(path, {("5106912", "Image"): f'=_xlfn.IMAGE("{url}")'})
    assert preview(data, "RFQ.xlsx", "job-1", sheet, 1).changes == []


def test_conflict_with_edit_made_in_app_after_download(tmp_path):
    from rfq.models import Cell, Sheet

    base, path = _download(tmp_path)
    current = Sheet.from_dict(base.to_dict())
    row = next(r for r in current.rows if r.product_id == "5106880")
    row.cells["ANSI"] = Cell("ANSI Z535.4", "manual_edit", "high", "colleague")  # changed in the app at v2
    data = _edit(path, {("5106880", "ANSI"): "ANSI Z535.1", ("5106880", "Temperature Range"): "-40 to 180 Deg F"})
    p = preview(data, "RFQ.xlsx", "job-1", current, 2, base=base)
    by = {(c.product_id, c.column): c for c in p.changes}
    assert by[("5106880", "ANSI")].status == "conflict" and "since your download" in by[("5106880", "ANSI")].message
    assert by[("5106880", "Temperature Range")].status == "ok"
    assert any("downloaded at version 1" in w for w in p.warnings)


def test_wrong_job_and_bad_files(tmp_path):
    sheet, path = _download(tmp_path, job_id="other-job")
    assert "different RFQ" in preview(path.read_bytes(), "RFQ.xlsx", "job-1", sheet, 1).errors[0]
    assert preview(b"not a zip", "RFQ.xlsx", "job-1", sheet, 1).errors
    assert "missing these columns" in preview(b"a,b\n1,2", "RFQ.csv", "job-1", sheet, 1).errors[0]
    assert ".xlsx, .xlsm, .xls or .csv" in preview(b"%PDF", "RFQ.pdf", "job-1", sheet, 1).errors[0]
    assert "Excel 97" in preview(b"not an xls", "RFQ.xls", "job-1", sheet, 1).errors[0]
    renamed = _edit(path, {}, rename=("Weight", "Wt"))
    assert "missing these columns: Weight" in preview(renamed, "RFQ.xlsx", "other-job", sheet, 1).errors[0]


def test_unknown_duplicate_and_missing_rows(tmp_path):
    sheet, path = _download(tmp_path)
    wb = openpyxl.load_workbook(path)
    ws = wb["RFQ"]
    ws.append(["9999999", "made up"] + [None] * 21)
    ws.delete_rows(3)  # 5106935 removed in Excel
    buf = io.BytesIO()
    wb.save(buf)
    p = preview(buf.getvalue(), "RFQ.xlsx", "job-1", sheet, 1)
    assert any("9999999 is not in this RFQ" in w for w in p.warnings)
    assert any("kept unchanged: 5106935" in w for w in p.warnings)
    ws.append(["5106912"] + [None] * 22)
    buf = io.BytesIO()
    wb.save(buf)
    assert any("more than once" in e for e in preview(buf.getvalue(), "RFQ.xlsx", "job-1", sheet, 1).errors)


def test_no_meta_compares_with_current(tmp_path):
    sheet, path = _download(tmp_path)
    data = _edit(path, {("5106880", "ANSI"): "ANSI Z535.1"}, drop_meta=True)
    p = preview(data, "RFQ.xlsx", "job-1", sheet, 1)
    assert p.ok and len(p.changes) == 1 and any("version stamp" in w for w in p.warnings)


def test_image_column_is_not_read_picture_is(tmp_path):
    sheet, path = _download(tmp_path)
    data = _edit(path, {("5106912", "Image"): "https://example.com/x.png",
                        ("5106935", "Picture"): "https://i.ferg-img.com/i/fergusonprod/new_primary"})
    p = preview(data, "RFQ.xlsx", "job-1", sheet, 1)
    assert [(c.product_id, c.column, c.status) for c in p.changes] == [("5106935", "Picture", "ok")]



def _export(fmt, what, sheet, report, path):
    from rfq.excel.exports import export
    from rfq.excel.writer import render_summary_bytes

    data, f = export(what, fmt, rfq_xlsx=path.read_bytes(), summary_xlsx=render_summary_bytes(sheet, report),
                     sheet=sheet, report=report)
    return data, f


def test_xls_download_keeps_values_colours_and_round_trips(tmp_path):
    import xlrd
    import xlwt

    result = run_sync(tmp_path / "run", eml("email-3"))
    path = render(result.sheet, tmp_path / "RFQ_v1.xlsx", result.report, meta={"job_id": "job-1", "version": "1"},
                  embed_images=False)
    data, f = _export("xls", "rfq", result.sheet, result.report, path)
    assert f.extension == ".xls" and data[:8] == bytes.fromhex("d0cf11e0a1b11ae1")  # real BIFF8 (OLE) file
    book = xlrd.open_workbook(file_contents=data, formatting_info=True)
    assert book.sheet_names()[:3] == ["RFQ", "Supplier", "Summary"] and book.sheet_by_name("_rfq_meta").visibility == 1
    rfq = book.sheet_by_name("RFQ")
    xlsx_rows = [list(r) for r in openpyxl.load_workbook(path)["RFQ"].iter_rows(values_only=True)]
    image_col = xlsx_rows[0].index("Image")
    for i, row in enumerate(xlsx_rows):
        for j, v in enumerate(row):
            got = rfq.cell_value(i, j)
            if j == image_col and isinstance(v, str) and v.startswith("=IMAGE"):
                assert got.startswith("https://")  # .xls has no IMAGE(): the address instead of a formula
            else:
                assert (got or None) == (v if v != "" else None), (i, j, v, got)
    fills = {book.colour_map.get(book.xf_list[rfq.cell_xf_index(i, j)].background.pattern_colour_index)
             for i in range(1, rfq.nrows) for j in range(rfq.ncols)}
    assert (0xD9, 0xD9, 0xD9) in fills and (0xFB, 0xE2, 0xD5) in fills  # grey missing, not-found row

    # user edits the .xls (rebuild it with one change, as Excel would save it)
    out = xlwt.Workbook()
    for s in book.sheets():
        ws = out.add_sheet(s.name, cell_overwrite_ok=True)
        for i in range(s.nrows):
            for j in range(s.ncols):
                ws.write(i, j, s.cell_value(i, j))
    header = [rfq.cell_value(0, j) for j in range(rfq.ncols)]
    row = next(i for i in range(rfq.nrows) if rfq.cell_value(i, 0) == "5106878")
    assert not rfq.cell_value(row, header.index("OSHA"))  # blank before the edit
    out.get_sheet(0).write(row, header.index("OSHA"), "OSHA 1926.956")
    import io as _io
    buf = _io.BytesIO()
    out.save(buf)
    p = preview(buf.getvalue(), "RFQ.xls", "job-1", result.sheet, 1)
    assert p.ok and [(c.product_id, c.column, c.status) for c in p.changes] == [("5106878", "OSHA", "ok")]


def test_csv_download_round_trips_even_from_european_excel(tmp_path):
    import csv as csvmod
    import io as _io

    result = run_sync(tmp_path / "run", eml("email-1"))
    path = render(result.sheet, tmp_path / "RFQ.xlsx", result.report, embed_images=False)
    data, f = _export("csv", "rfq", result.sheet, result.report, path)
    assert data.startswith(b"\xef\xbb\xbf") and f.extension == ".csv"
    rows = list(csvmod.reader(_io.StringIO(data.decode("utf-8-sig"))))
    assert rows[0][-1] == "Review notes" and rows[0][:-1][0] == "product_id"
    by = {r[0]: dict(zip(rows[0], r)) for r in rows[1:]}
    assert by["5106912"]["Image"].startswith("https://") and by["5106912"]["Temperature Range"] == "-60 to 250 Deg F"
    assert "ANSI: missing" in by["5106880"]["Review notes"]
    # unchanged CSV: no changes; edited + saved with ';' in Windows-1252 (European Excel): still read
    assert preview(data, "RFQ.csv", "job-1", result.sheet, 1).changes == []
    by["5106880"]["ANSI"] = "ANSI Z535.1"
    by["5106880"]["Lettering"] = "Caution Open Trench – Café"  # non-ASCII survives cp1252
    buf = _io.StringIO()
    w = csvmod.writer(buf, delimiter=";")
    w.writerow(rows[0])
    for r in rows[1:]:
        w.writerow([by[r[0]][h] for h in rows[0]])
    p = preview(buf.getvalue().encode("cp1252"), "RFQ.csv", "job-1", result.sheet, 1)
    got = {(c.product_id, c.column): c for c in p.changes}
    assert p.ok and set(got) == {("5106880", "ANSI"), ("5106880", "Lettering")}
    assert got[("5106880", "Lettering")].uploaded.endswith("Café")
    assert not any("Review notes" in w for w in p.warnings)  # our own column is not reported as extra
    assert any("version stamp" in w for w in p.warnings)


def test_csv_injection_guard(tmp_path):
    from rfq.excel.exports import _csv_safe

    assert _csv_safe('=HYPERLINK("x")') == """'=HYPERLINK("x")"""
    assert _csv_safe("+1") == "'+1" and _csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert _csv_safe("-cmd") == "'-cmd" and _csv_safe("-60 to 250 Deg F") == "-60 to 250 Deg F"
    from rfq.excel.importer import _uncsv

    assert _uncsv("'=x") == "=x"  # read back as text, then refused by validation as a formula


def test_summary_exports(tmp_path):
    import xlrd

    result = run_sync(tmp_path / "run", eml("email-3"))
    path = render(result.sheet, tmp_path / "RFQ.xlsx", result.report, embed_images=False)
    csv_data, _ = _export("csv", "summary", result.sheet, result.report, path)
    assert "RFQ quality summary" in csv_data.decode("utf-8-sig") and "MTX-4409-XQ" in csv_data.decode("utf-8-sig")
    xls, _ = _export("xls", "summary", result.sheet, result.report, path)
    assert xlrd.open_workbook(file_contents=xls).sheet_names() == ["Summary", "Notes"]
    import pytest as _pytest

    from rfq.excel.exports import ExportError
    with _pytest.raises(ExportError):
        _export("pdf", "rfq", result.sheet, result.report, path)
