"""Product pictures embedded in the RFQ workbook (so the image is visible in any spreadsheet app,
not only Excel 365's IMAGE() formula).

prefetch() downloads thumbnails into a disk cache (async, before the workbook is written);
cached() is what the synchronous Excel writer uses. Only Ferguson's image hosts are fetched: a
picture URL typed in by a user that points elsewhere stays a link and is never downloaded.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from rfq.config import ROOT

log = logging.getLogger(__name__)

IMAGE_HOSTS = ("i.ferg-img.com",)
MAX_BYTES = 3 * 1024 * 1024
MAX_PIXELS = 25_000_000  # decompression-bomb guard
THUMB_PX = 100
FAIL_TTL = 24 * 3600


def primary_picture(value: str) -> str:
    """Picture cells can hold several URLs separated by | (e.g. a top view and the main shot).
    The one to show is the '_primary' image, otherwise the first web address."""
    urls = [u.strip() for u in (value or "").split("|") if u.strip().startswith(("http://", "https://"))]
    if not urls:
        return ""
    return next((u for u in urls if "_primary" in u), urls[0])


def cache_dir() -> Path:
    path = Path(os.environ.get("IMAGE_CACHE_DIR", ROOT / "out" / "image_cache"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:40]


def allowed(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and (parsed.hostname or "") in IMAGE_HOSTS


def cached(url: str) -> Path | None:
    path = cache_dir() / f"{_key(url)}.png"
    return path if path.exists() else None


def _failed_recently(url: str) -> str | None:
    marker = cache_dir() / f"{_key(url)}.fail"
    if marker.exists() and time.time() - marker.stat().st_mtime < FAIL_TTL:
        return marker.read_text(encoding="utf-8")[:200]
    return None


def _thumbnail(data: bytes) -> bytes:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    with Image.open(io.BytesIO(data)) as probe:
        probe.verify()  # truncated or not really an image
    with Image.open(io.BytesIO(data)) as img:
        if img.width * img.height > MAX_PIXELS:
            raise ValueError("image too large")
        img = img.convert("RGB")
        img.thumbnail((THUMB_PX, THUMB_PX))
        # centre on a white square so it fills the cell evenly
        canvas = Image.new("RGB", (THUMB_PX, THUMB_PX), "white")
        canvas.paste(img, ((THUMB_PX - img.width) // 2, (THUMB_PX - img.height) // 2))
        out = io.BytesIO()
        canvas.save(out, format="PNG", optimize=True)
        return out.getvalue()


def _fetch_url(url: str) -> str:
    """Ask the image CDN for a small JPEG instead of the full-size original."""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}fmt=jpg&w=300" if (urlparse(url).hostname or "") == "i.ferg-img.com" else url


async def _download(url: str, client: httpx.AsyncClient) -> None:
    async with client.stream("GET", _fetch_url(url), follow_redirects=False, timeout=15) as resp:
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        ctype = resp.headers.get("content-type", "")
        if not ctype.startswith("image/"):
            raise ValueError(f"not an image ({ctype or 'no content type'})")
        data = bytearray()
        async for chunk in resp.aiter_bytes():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise ValueError("image larger than 3 MB")
    png = await asyncio.to_thread(_thumbnail, bytes(data))
    target = cache_dir() / f"{_key(url)}.png"
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(png)
    tmp.replace(target)


async def prefetch(urls: list[str], client: httpx.AsyncClient | None = None,
                   concurrency: int = 4) -> dict[str, str]:
    """Downloads every missing thumbnail. Returns {url: reason} for pictures that could not be embedded."""
    problems: dict[str, str] = {}
    todo = []
    for url in dict.fromkeys(u for u in urls if u):
        if not allowed(url):
            problems[url] = "not a Ferguson image address, so it is not downloaded (kept as a link)"
        elif cached(url) is None:
            reason = _failed_recently(url)
            if reason:
                problems[url] = reason
            else:
                todo.append(url)
    if not todo:
        return problems
    own = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": "RFQ-Agent/1.0 (product thumbnails)"})
    sem = asyncio.Semaphore(concurrency)

    async def one(url: str) -> None:
        async with sem:
            try:
                await _download(url, client)
            except Exception as e:  # never fail the RFQ because of a picture
                reason = f"picture could not be downloaded ({type(e).__name__}: {str(e)[:80]})"
                problems[url] = reason
                (cache_dir() / f"{_key(url)}.fail").write_text(reason, encoding="utf-8")

    try:
        await asyncio.gather(*(one(u) for u in todo))
    finally:
        if own:
            await client.aclose()
    return problems
