from __future__ import annotations

import asyncio

import pytest
from helpers import live_html

from rfq.config import RunOptions
from rfq.eta import Progress
from rfq.extract_ids import extract
from rfq.lookup import resolve as resolve_mod
from rfq.lookup.cache import MemoryCache
from rfq.lookup.live import LiveResult, LiveUnavailable, looks_blocked, parse_product_page
from rfq.lookup.specsheet import extract_values
from rfq.models import Cell

URL = "https://www.ferguson.com/product/some-slug/{}.html"


def test_parse_live_product_with_jsonld():
    r = parse_product_page(live_html("p5106912"), "5106912", URL.format(5106912), read_on="2026-10-16")
    assert r.status == "found"
    v = {k: c.value for k, c in r.cells.items()}
    assert v["Description"] == '6 in x 1000 ft Blue Detector Tape "CAUTION BURIED WATER LINE BELOW"'
    assert v["Application"] == "Water|Marking|Underground"  # comma list → pipe list like the catalog
    assert v["Material"] == "Aluminum Foil|Plastic" and v["Weight"] == "14.25 lb"
    assert v["Image"] == v["Picture"] == "https://i.ferg-img.com/i/fergusonprod/5106912_1815492_primary"
    assert all(c.source_type == "ferguson_page" and "2026-10-16" in c.source for c in r.cells.values())
    assert all(c.url == URL.format(5106912) for c in r.cells.values())  # every value links to the page
    s = {k: c.value for k, c in r.supplier.items()}
    assert s["Price (USD)"] == "139.02" and s["Brand"] == "Presco" and s["Supplier"] == "Ferguson"
    assert s["Manufacturer Part #"] == "SD6105B52" and s["Product page"] == URL.format(5106912)


def test_parse_live_product_without_jsonld():
    r = parse_product_page(live_html("p233900"), "233900", URL.format(233900))
    assert r.status == "found" and r.cells["Description"].value == "1000 ft. Detectable Gas Tape"
    assert r.cells["Image"].value.endswith("233900_4972162_primary")


def test_parse_cleans_ferguson_pseudo_tags():
    r = parse_product_page(live_html("p1376044"), "1376044", URL.format(1376044))
    assert "Pro-Line's" in r.cells["Product details"].value and "<CQUOTA/>" not in r.cells["Product details"].value


def test_parse_redirect_to_homepage_is_not_found():
    r = parse_product_page(live_html("x9999991"), "9999991", "https://www.ferguson.com/")
    assert r.status == "not_found"


def test_parse_page_for_another_product_is_not_trusted():
    r = parse_product_page(live_html("p5106912"), "5106935", URL.format(5106912))
    assert r.status == "not_found"  # the URL is for a different ID


@pytest.mark.parametrize("status,html,title", [
    (403, "<html></html>", ""),
    (200, "<html><title>Access Denied</title></html>", "Access Denied"),
    (200, "<div id='px-captcha'></div>", ""),
])
def test_block_detection(status, html, title):
    assert looks_blocked(status, html, title)
    assert parse_product_page(html, "5106912", URL.format(5106912), status).status == "blocked"


def test_empty_page_with_right_url_is_blocked_not_found():
    r = parse_product_page("<html><body>loading</body></html>", "5106912", URL.format(5106912))
    assert r.status == "blocked"


class FakeLive:
    """Stands in for LiveFerguson with canned results."""

    results: dict[str, LiveResult] = {}
    requested: list[str] = []
    waited_s = 0.0

    def __init__(self, *a, **k): ...
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return None
    async def lookup(self, pid):
        FakeLive.requested.append(pid)
        return self.results.get(pid, LiveResult("not_found", "not on ferguson.com"))


def _resolve(body: str, monkeypatch, results=None, unavailable=False):
    if unavailable:
        class Down(FakeLive):
            async def __aenter__(self): raise LiveUnavailable("Chrome is not reachable")
        monkeypatch.setattr(resolve_mod, "LiveFerguson", Down)
    else:
        FakeLive.results = results or {}
        monkeypatch.setattr(resolve_mod, "LiveFerguson", FakeLive)
    items = extract(body).items
    opts = RunOptions(offline=False, use_llm=False, use_pdfs=False, serpapi_key="")
    return asyncio.run(resolve_mod.resolve(items, opts, MemoryCache(), Progress()))


def test_live_wins_and_difference_is_noted(monkeypatch):
    src = "Ferguson product page X, read 2026-10-16"
    live = LiveResult("found", cells={"Width": Cell("3 in", "ferguson_page", "high", src),
                                      "Lettering": Cell("Changed lettering", "ferguson_page", "high", src)})
    sheet = _resolve("5106935", monkeypatch, {"5106935": live})
    row = sheet.rows[0]
    assert row.lookup_source == "live" and row.value("Lettering") == "Changed lettering"
    # not on the live page: the catalog value is kept with the catalog's own source
    assert row.value("ASTM") and row.cells["ASTM"].source_type != "ferguson_page"
    assert any("Lettering: live page says" in n.note for n in sheet.notes)
    assert not any(n.note.startswith("Width") for n in sheet.notes)  # same value, unit formatting only


def test_live_only_product_found(monkeypatch):
    live = LiveResult("found", cells={"Description": Cell("6 in. tape", "ferguson_page", "high", "page")})
    sheet = _resolve("225123", monkeypatch, {"225123": live})
    assert sheet.rows[0].lookup_status == "Found"
    assert any("Not in the backup catalog" in n.note for n in sheet.notes)


def test_live_blocked_falls_back_to_catalog(monkeypatch):
    sheet = _resolve("5106912", monkeypatch, {"5106912": LiveResult("blocked", "HTTP 403")})
    row = sheet.rows[0]
    assert row.lookup_status == "Found" and row.lookup_source == "catalog"
    assert any("Product page could not be read (HTTP 403)" in n.note for n in sheet.notes)


def test_not_live_not_catalog_is_not_found(monkeypatch):
    sheet = _resolve("9677533", monkeypatch, {})
    row = sheet.rows[0]
    assert row.lookup_status == "Not found" and not row.cells
    assert "not on ferguson.com and not in the backup catalog" in row.not_found_reason


def test_chrome_down_uses_catalog_with_warning(monkeypatch):
    sheet = _resolve("5106912 9677533", monkeypatch, unavailable=True)
    assert sheet.rows[0].lookup_status == "Found" and sheet.rows[1].lookup_status == "Not found"
    assert any("Product pages could not be read" in w for w in sheet.warnings)


def test_live_cache_and_cooldown():
    from rfq.lookup.live import COOLDOWN_FLAG, LiveFerguson

    async def go():
        cache = MemoryCache()
        live = LiveFerguson("http://127.0.0.1:1", cache)
        await cache.set_json("lookup:5106912", LiveResult("found", url="u").to_json(), 60)
        hit = await live.lookup("5106912")
        await cache.set_flag(COOLDOWN_FLAG, 60)
        cooled = await live.lookup("5106935")
        return hit, cooled

    hit, cooled = asyncio.run(go())
    assert hit.from_cache and hit.status == "found"
    assert cooled.status == "blocked" and "cool-down" in cooled.reason


FAMILY_SHEET = "Material Thicknesses\n2, 2.5, 3, 4 and 6 Mil\nRoll Lengths 200', 300'"
SINGLE_SHEET = "Overall Thickness:\n5 mil\nStandard Widths: 2\" | 3\""
ASTM_SHEET = "DETECTABLE TAPE (5.0 MIL)\n• ASTM D2103-08: films\n• ASTM D882-09: tensile\n• ASTM D2103-08 again"


def test_spec_sheet_family_list_is_ambiguous():
    assert "Thickness" not in extract_values(FAMILY_SHEET, "u")


def test_spec_sheet_single_labeled_value():
    cell = extract_values(SINGLE_SHEET, "https://api.ferguson.com/x")["Thickness"]
    assert cell.value == "5 mil" and cell.source_type == "spec_sheet" and '"Thickness: 5 mil"' in cell.source


def test_spec_sheet_astm_list_with_quotes():
    values = extract_values(ASTM_SHEET, "u")
    assert values["ASTM"].value == "ASTM D-2103|ASTM D-882"
    assert values["Thickness"].value == "5 mil"
    assert "ASTM D2103-08" in values["ASTM"].source  # verbatim quote


def test_spec_sheet_host_allowlist():
    import httpx

    from rfq.lookup.specsheet import read_spec_sheet

    async def go():
        async with httpx.AsyncClient() as client:
            return await read_spec_sheet("https://evil.example.com/x.pdf", {}, MemoryCache(), client)

    result = asyncio.run(go())
    assert not result.ok and "allowlist" in result.reason
