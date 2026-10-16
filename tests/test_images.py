"""Pictures embedded in the RFQ workbook: visible in any spreadsheet app, never fetched from strange hosts."""
from __future__ import annotations

import asyncio
import io

import httpx
import openpyxl
import pytest
from helpers import eml, run_sync

from rfq.excel import images
from rfq.excel.writer import render


@pytest.fixture(autouse=True)
def image_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path / "cache"))


def _png(size=(400, 300), color=(0, 68, 106)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_prefetch_makes_thumbnails_and_embeds_them(tmp_path):
    result = run_sync(tmp_path / "run", eml("email-1"))
    urls = [r.value("Picture") for r in result.sheet.rows]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=_png(), headers={"content-type": "image/jpeg"})

    async def go():
        async with _client(handler) as c:
            return await images.prefetch(urls, c)

    assert asyncio.run(go()) == {}
    assert all("fmt=jpg&w=300" in u for u in calls)  # small version from the CDN, not the original
    path = render(result.sheet, tmp_path / "RFQ.xlsx", result.report)
    wb = openpyxl.load_workbook(path)
    ws = wb["RFQ"]
    assert len(ws._images) == 6 and {img.anchor._from.col for img in ws._images} == {20}  # column U = Image
    assert ws["U2"].value.startswith('=IMAGE("https://')  # values unchanged (reference format)
    assert ws["V2"].hyperlink is not None  # Picture is a clickable link
    asyncio.run(go())
    assert len(calls) == 6  # second run served from the disk cache


def test_bad_pictures_never_break_the_rfq(tmp_path):
    good = "https://i.ferg-img.com/i/fergusonprod/1_primary"
    responses = {
        "https://i.ferg-img.com/i/fergusonprod/html_primary": httpx.Response(200, text="<html>", headers={"content-type": "text/html"}),
        "https://i.ferg-img.com/i/fergusonprod/broken_primary": httpx.Response(200, content=b"\xff\xd8 not really", headers={"content-type": "image/jpeg"}),
        "https://i.ferg-img.com/i/fergusonprod/404_primary": httpx.Response(404),
        "https://i.ferg-img.com/i/fergusonprod/huge_primary": httpx.Response(200, content=b"0" * (images.MAX_BYTES + 10), headers={"content-type": "image/jpeg"}),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        base = str(request.url).split("?")[0]
        return responses.get(base) or httpx.Response(200, content=_png(), headers={"content-type": "image/jpeg"})

    urls = [good, *responses, "https://evil.example.com/a.png", "http://i.ferg-img.com/insecure", "javascript:x"]

    async def go():
        async with _client(handler) as c:
            return await images.prefetch(urls, c)

    problems = asyncio.run(go())
    assert good not in problems and images.cached(good)
    assert set(problems) == set(urls) - {good}
    assert "not a Ferguson image address" in problems["https://evil.example.com/a.png"]
    assert "HTTP 404" in problems["https://i.ferg-img.com/i/fergusonprod/404_primary"]
    assert "3 MB" in problems["https://i.ferg-img.com/i/fergusonprod/huge_primary"]
    # failures are remembered for a day, so regenerating a version does not wait on them again
    calls = []

    def counting(request):
        calls.append(request.url)
        return httpx.Response(500)

    async def again():
        async with _client(counting) as c:
            return await images.prefetch(urls, c)

    asyncio.run(again())
    assert calls == []


def test_missing_pictures_are_noted_on_the_rfq(tmp_path, monkeypatch):
    from rfq import pipeline

    async def fail(urls, client=None, concurrency=4):
        return {u: "picture could not be downloaded (ConnectError: offline)" for u in urls}

    monkeypatch.setattr(pipeline.images, "prefetch", fail)
    result = run_sync(tmp_path / "run", eml("email-1"))
    asyncio.run(pipeline.add_pictures(result.sheet))
    assert sum("Picture not embedded" in n.note for n in result.sheet.notes) == 6


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")  # the warning is the point
def test_decompression_bomb_is_refused():
    from PIL import Image

    big = io.BytesIO()
    Image.new("1", (6000, 6000)).save(big, format="PNG")  # 36 M pixels, tiny file
    with pytest.raises(Exception):
        images._thumbnail(big.getvalue())


def test_picture_with_several_urls_embeds_the_primary_one(tmp_path):
    from rfq.models import Cell, Row, Sheet
    from rfq.validation import validate

    two = "https://i.ferg-img.com/i/fergusonprod/7099537_2966898_top_view|https://i.ferg-img.com/i/fergusonprod/7099537_3518136_primary"
    row = Row(product_id="7099537", kind="ferguson", lookup_status="Found")
    row.cells["Image"] = Cell(two, "ferguson_page", "high", "catalog")
    row.cells["Picture"] = Cell(two, "ferguson_page", "high", "catalog")
    asked = []

    def handler(request):
        asked.append(str(request.url).split("?")[0])
        return httpx.Response(200, content=_png(), headers={"content-type": "image/jpeg"})

    async def go():
        async with _client(handler) as c:
            return await images.prefetch([images.primary_picture(two)], c)

    assert asyncio.run(go()) == {} and asked == ["https://i.ferg-img.com/i/fergusonprod/7099537_3518136_primary"]
    ws = openpyxl.load_workbook(render(Sheet(rows=[row]), tmp_path / "x.xlsx"))["RFQ"]
    assert ws["U2"].value == '=IMAGE("https://i.ferg-img.com/i/fergusonprod/7099537_3518136_primary")'  # one valid URL
    assert ws["V2"].value == two and ws["V2"].hyperlink.target.endswith("_primary")  # data kept as written
    assert len(ws._images) == 1
    assert validate("Picture", two) == two
    with pytest.raises(Exception):
        validate("Picture", "https://ok/x.png|javascript:alert(1)")
