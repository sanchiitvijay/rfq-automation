from __future__ import annotations

from helpers import eml, make_eml, xlsx_bytes

from rfq.config import MAX_IDS
from rfq.extract_ids import extract
from rfq.parse_email import parse_eml, parse_text

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def ids(raw: bytes) -> list[tuple[str, str]]:
    p = parse_eml(raw)
    return [(i.product_id, i.kind) for i in extract(p.body, p.attachments).items]


def test_email1_ids_in_body():
    assert ids(eml("email-1")) == [(x, "ferguson") for x in
                                   ["5106912", "5106935", "5106914", "5106966", "5106891", "5106880"]]


def test_email2_ids_in_attachment_with_qty():
    p = parse_eml(eml("email-2"))
    items = extract(p.body, p.attachments).items
    assert [i.product_id for i in items] == ["1376044", "1432040", "233900", "4742155", "5106899", "9677514",
                                             "7099537", "225123"]
    assert items[0].qty == "10" and items[-1].qty == "20"
    assert all(i.origin == "attachment:rfq_items.xlsx" for i in items)


def test_email3_mixed_competitor_codes_and_brands():
    p = parse_eml(eml("email-3"))
    items = extract(p.body, p.attachments).items
    assert [(i.product_id, i.kind) for i in items] == [
        ("5106878", "ferguson"), ("5106907", "ferguson"), ("4570880", "ferguson"), ("9677531", "ferguson"),
        ("17783-79-3000", "competitor"), ("31-024", "competitor"), ("MTX-4409-XQ", "competitor")]
    brands = {i.product_id: i.brand for i in items}
    assert brands["17783-79-3000"] == "Mutual Industries" and brands["31-024"] == "Empire"
    assert brands["MTX-4409-XQ"] is None  # never invent a brand


def test_email4_messy_forward_duplicate_and_hash():
    p = parse_eml(eml("email-4"))
    items = extract(p.body, p.attachments).items
    assert [i.product_id for i in items] == ["5106926", "8067331", "1844552", "4783795", "5106888", "9677533",
                                             "17774-79-3000"]
    first = items[0]
    assert first.raw_token == "#5106926" and first.occurrences == 2 and first.qty == "40"
    assert items[2].qty is None  # several IDs on one line: no qty guessed


def test_every_token_appears_verbatim():
    for name in ("email-1", "email-3", "email-4"):
        p = parse_eml(eml(name))
        for item in extract(p.body).items:
            assert item.raw_token in p.body


def test_lookalike_numbers_are_masked():
    body = """Call me at 555-123-4567 or +1 (555) 987-6543.
PO #4500123 and order no. 7781234 are paid. Invoice: 1234567
Date 2026-10-15, 15/10/2026. See https://example.com/item/5106912 and mail 5106935@x.com
Real item: 5106914 x 12 rolls
"""
    items = extract(body).items
    assert [i.product_id for i in items] == ["5106914"]
    assert items[0].qty == "12"


def test_comma_separated_and_inline_ids():
    items = extract("Need 1844552 , 4783795,5106888 and also #9677533 - red tape").items
    assert [i.product_id for i in items] == ["1844552", "4783795", "5106888", "9677533"]


def test_size_words_are_not_codes():
    assert extract("3-inch tape, 6-in wide, Q4-26 round, 2-pack").items == []


def test_html_only_email():
    raw = make_eml(html="<html><body><p>Items:</p><ul><li>5106912</li><li>5106935</li></ul></body></html>")
    assert [x for x, _ in ids(raw)] == ["5106912", "5106935"]


def test_quoted_printable_soft_breaks():
    p = parse_eml(eml("email-2"))
    assert "older items" in p.body  # "ol=\nder" joined back


def test_zero_ids_gives_warning():
    result = extract("Hello, please send me a quote for tape. Thanks!")
    assert result.items == [] and any("No product IDs" in w for w in result.warnings)


def test_attachment_unexpected_header_scans_cells():
    data = xlsx_bytes([["Something", "Else"], ["see 5106912", "and 5106935"]])
    raw = make_eml("list attached", attachments=[("list.xlsx", data, XLSX)])
    assert [x for x, _ in ids(raw)] == ["5106912", "5106935"]


def test_attachment_multiple_sheets_dedupe():
    data = xlsx_bytes([["Item number", "Qty"], [5106912, 3], ["5106935", 4]], sheets=2)
    p = parse_eml(make_eml("", attachments=[("a.xlsx", data, XLSX)]))
    items = extract(p.body, p.attachments).items
    assert [i.product_id for i in items] == ["5106912", "5106935"]
    assert items[0].occurrences == 2


def test_attachment_empty_sheet():
    data = xlsx_bytes([])
    p = parse_eml(make_eml("hi", attachments=[("empty.xlsx", data, XLSX)]))
    result = extract(p.body, p.attachments)
    assert result.items == []


def test_csv_attachment():
    raw = make_eml("", attachments=[("items.csv", b"Part,Qty\n5106912,5\nMTX-4409-XQ,1\n", "text/csv")])
    assert ids(raw) == [("5106912", "ferguson"), ("MTX-4409-XQ", "competitor")]


def test_broken_or_password_protected_xlsx_is_noted():
    p = parse_eml(make_eml("5106912", attachments=[("locked.xlsx", b"\xd0\xcf\x11\xe0not a zip", XLSX)]))
    result = extract(p.body, p.attachments)
    assert [i.product_id for i in result.items] == ["5106912"]
    assert any("could not be opened" in w for w in result.warnings)


def test_legacy_xls_is_noted():
    p = parse_eml(make_eml("hi", attachments=[("old.xls", b"x", "application/vnd.ms-excel")]))
    assert any(".xls" in w for w in extract(p.body, p.attachments).warnings)


def test_non_sheet_attachment_ignored_with_note():
    p = parse_eml(make_eml("5106912", attachments=[("photo.png", b"\x89PNG", "image/png")]))
    assert p.attachments == [] and any("photo.png" in w for w in p.warnings)


def test_id_limit():
    body = "\n".join(str(1000000 + i) for i in range(MAX_IDS + 5))
    result = extract(body)
    assert len(result.items) == MAX_IDS and any("only the first" in w for w in result.warnings)


def test_pasted_text():
    p = parse_text("Please quote:\r\n5106912\r\n", subject="RFQ", sender="a@b.c")
    assert extract(p.body).items[0].product_id == "5106912"
