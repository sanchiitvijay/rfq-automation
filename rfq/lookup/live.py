"""Live product lookup on ferguson.com through the user's own Chrome (remote debugging port 9333).

Using a real, already-opened Chrome profile is what keeps ferguson.com from treating the lookup as
a bot. On top of that the lookup is polite: at most a couple of tabs at once across all workers, a
minimum gap between page loads, images/fonts not downloaded, and a cool-down after repeated blocks.
There is no captcha solving or fingerprint spoofing: when the site blocks us, we fall back to the
backup catalog and say so.
"""
from __future__ import annotations

import asyncio
import html as htmllib
import json
import logging
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

from bs4 import BeautifulSoup

from rfq.lookup.cache import BLOCK_COOLDOWN, BLOCKS_BEFORE_COOLDOWN, LOOKUP_TTL, Cache
from rfq.models import Cell

log = logging.getLogger(__name__)

PRODUCT_URL = "https://www.ferguson.com/product/{pid}.html"  # redirects to the canonical product page
COOLDOWN_FLAG = "blocked:ferguson"
MIN_GAP_S = 2.0

LABELS = {
    "Length": "Length", "Thickness": "Thickness", "Weight": "Weight", "Width": "Width",
    "Color Finish Name": "Color Finish", "Color Finish": "Color Finish", "Color": "Color Finish",
    "Lettering": "Lettering", "Material": "Material", "Material Type": "Material Type",
    "Tool Type": "Tool Type", "Temperature Range": "Temperature Range", "ANSI": "ANSI",
    "Application": "Application", "OSHA": "OSHA", "ASTM": "ASTM", "UL Listed": "UL Listed",
    "Number of Tools Included": "No of Tools", "Number of Tools": "No of Tools", "No of Tools": "No of Tools",
    "Waterworks Application": "Waterworks Application",
}
EXTRA_LABELS = {"UPC": "UPC"}
LIST_COLUMNS = {"Application", "Material", "ASTM", "Waterworks Application"}  # "a, b" → "a|b" like the catalog
BLOCK_MARKERS = (
    "access denied", "pardon our interruption", "px-captcha", "captcha-delivery", "verify you are a human",
    "are you a robot", "request unsuccessful", "_incapsula_resource", "unusual traffic",
)

Status = Literal["found", "not_found", "blocked", "error"]


@dataclass
class LiveResult:
    status: Status
    reason: str = ""
    url: str = ""
    cells: dict[str, Cell] = field(default_factory=dict)
    supplier: dict[str, Cell] = field(default_factory=dict)
    from_cache: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LiveResult:
        data = dict(data)
        data.pop("extras", None)  # cached by an earlier version
        data["cells"] = {k: Cell(**v) for k, v in data.get("cells", {}).items()}
        data["supplier"] = {k: Cell(**v) for k, v in data.get("supplier", {}).items()}
        return cls(**data)


class LiveUnavailable(RuntimeError):
    """Chrome is not reachable on the debugging port."""


_ENTITY_TAGS = {"<CQUOTA/>": "'", "<QUOTA/>": '"', "<DQUOTA/>": '"', "<AMP/>": "&"}


def _clean(value: str) -> str:
    """ferguson.com writes some characters as pseudo-tags (Pro-Line<CQUOTA/>s → Pro-Line's)."""
    value = htmllib.unescape(value)
    for tag, char in _ENTITY_TAGS.items():
        value = value.replace(tag, char)
    return re.sub(r"\s+", " ", value).strip()


def _text(node: Any) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _product_jsonld(soup: BeautifulSoup) -> dict[str, Any] | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in data if isinstance(data, list) else [data]:
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                return obj
    return None


def looks_blocked(status: int | None, html: str, title: str) -> str | None:
    if status in (403, 429, 503):
        return f"HTTP {status}"
    head = (title + " " + html[:20000]).lower()
    for marker in BLOCK_MARKERS:
        if marker in head:
            return f"bot protection page ('{marker}')"
    return None


def parse_product_page(html: str, pid: str, final_url: str, status: int | None = 200,
                       read_on: str | None = None) -> LiveResult:
    """Pure parser for a ferguson.com page (tested against saved fixtures)."""
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    blocked = looks_blocked(status, html, title)
    if blocked:
        return LiveResult("blocked", blocked, final_url)
    if f"/{pid}.html" not in final_url:
        return LiveResult("not_found", "not on ferguson.com (product URL redirects to another page)", final_url)
    product = _product_jsonld(soup)
    if product and str(product.get("sku", "")).strip() != pid:
        product = None
    page_is_product = bool(re.search(rf'data-sku="{pid}"', html)) or bool(
        soup.select(".c-product-details__specs__specsAttributes"))
    if not product and not page_is_product:
        return LiveResult("blocked", "page loaded without product data (possibly a challenge page)", final_url)
    product = product or {}  # some pages carry no JSON-LD; the HTML fallbacks below cover them

    read_on = read_on or date.today().isoformat()
    page_url = final_url.split("?")[0]
    source = f"Ferguson product page, read live {read_on}"
    cells: dict[str, Cell] = {}
    supplier: dict[str, Cell] = {}

    def put(column: str, value: str) -> None:
        value = _clean(value)
        if value:
            cells[column] = Cell(value, "ferguson_page", "high", source, page_url)

    def put_supplier(column: str, value: str) -> None:
        value = _clean(value)
        if value:
            supplier[column] = Cell(value, "ferguson_page", "high", source, page_url)

    h1 = soup.select_one("h1")
    put("Description", str(product.get("name", "")) or (_text(h1) if h1 else ""))
    description = product.get("description")
    if not description:
        description = [_text(li) for li in soup.select("ul.js-product-features-list li")]
    if isinstance(description, list):
        put("Product details", "|".join(_clean(str(d)) for d in description if _clean(str(d))))
    elif isinstance(description, str):
        put("Product details", description)
    images = product.get("image")
    image = images[0] if isinstance(images, list) and images else images if isinstance(images, str) else ""
    if not image:
        m = re.search(rf"https://i\.ferg-img\.com/i/fergusonprod/{pid}_\d+_primary", html)
        image = m.group(0) if m else ""
    if image:
        put("Image", image)
        put("Picture", image)

    put_supplier("Supplier", "Ferguson")
    put_supplier("Product page", page_url)
    for row in soup.select(".c-product-details__specs__specsAttributes"):
        parts = row.select(".c-product-details__specs__attribute")
        if len(parts) != 2:
            continue
        label, value = _text(parts[0]), _text(parts[1])
        if label in LABELS:
            column = LABELS[label]
            if column in LIST_COLUMNS:
                value = "|".join(v.strip() for v in value.split(",") if v.strip())
            put(column, value)
        elif label in EXTRA_LABELS and value:
            put_supplier(EXTRA_LABELS[label], value)

    brand = product.get("brand")
    if isinstance(brand, dict) and brand.get("name"):
        put_supplier("Brand", str(brand["name"]))
    offers = product.get("offers")
    if isinstance(offers, dict):
        if offers.get("price"):
            put_supplier("Price (USD)", str(offers["price"]))
        if offers.get("availability"):
            put_supplier("Availability", str(offers["availability"]).rsplit("/", 1)[-1])
    text = soup.get_text(" ")
    mfr = re.search(r"Manufacturer Part #\s*([A-Za-z0-9\-./]+)", text)
    if mfr:
        put_supplier("Manufacturer Part #", mfr.group(1))
    return LiveResult("found", "", final_url, cells, supplier)


class LiveFerguson:
    """One CDP connection shared by all lookups of a job."""

    def __init__(self, cdp_url: str, cache: Cache, timeout_s: float = 20.0, concurrency: int = 2,
                 rate_per_minute: int = 12) -> None:
        self.cdp_url = cdp_url
        self.cache = cache
        self.timeout_ms = int(timeout_s * 1000)
        self.concurrency = concurrency
        self.rate_per_minute = rate_per_minute
        self.waited_s = 0.0  # time spent waiting for the rate limit (shown in the job's notes)
        self._pw: Any = None
        self._context: Any = None

    async def __aenter__(self) -> LiveFerguson:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        try:
            browser = await self._pw.chromium.connect_over_cdp(self.cdp_url, timeout=5000)
        except Exception as e:
            await self._pw.stop()
            raise LiveUnavailable(f"Chrome is not reachable at {self.cdp_url} ({type(e).__name__})") from e
        self._context = browser.contexts[0] if browser.contexts else await browser.new_context()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._pw:  # stop() only drops our connection; the user's Chrome stays open
            await self._pw.stop()

    async def lookup(self, pid: str) -> LiveResult:
        cached = await self.cache.get_json(f"lookup:{pid}")
        if cached:
            result = LiveResult.from_json(cached)
            result.from_cache = True
            return result
        if await self.cache.has_flag(COOLDOWN_FLAG):
            return LiveResult("blocked", "ferguson.com cool-down active after repeated blocks")

        result = await self._fetch(pid)
        if result.status in ("blocked", "error"):
            await asyncio.sleep(4 + random.random() * 4)  # back off once, then retry
            result = await self._fetch(pid)
        if result.status == "blocked":
            if await self.cache.incr_window("ferguson:blocks", 600) >= BLOCKS_BEFORE_COOLDOWN:
                await self.cache.set_flag(COOLDOWN_FLAG, BLOCK_COOLDOWN)
        if result.status in ("found", "not_found"):
            ttl = LOOKUP_TTL if result.status == "found" else 3600
            await self.cache.set_json(f"lookup:{pid}", result.to_json(), ttl)
        return result

    async def _fetch(self, pid: str) -> LiveResult:
        # spacing (60 s / limit) avoids bursts; the sliding window guarantees the per-minute cap
        gap = max(MIN_GAP_S, 60.0 / self.rate_per_minute)
        async with self.cache.slot("ferguson", self.concurrency, gap + random.random() * 0.5):
            self.waited_s += await self.cache.rate("ferguson", self.rate_per_minute, 60.0)
            page = await self._context.new_page()
            try:
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ("image", "media", "font")
                    else route.continue_(),
                )
                response = await page.goto(PRODUCT_URL.format(pid=pid), wait_until="domcontentloaded",
                                           timeout=self.timeout_ms)
                try:
                    await page.wait_for_selector(".c-product-details__specs__specsAttributes",
                                                 state="attached", timeout=6000)
                except Exception:
                    pass  # not-found / blocked pages never show the spec table
                html = await page.content()
                return parse_product_page(html, pid, page.url, response.status if response else None)
            except Exception as e:
                name = type(e).__name__
                reason = "timed out" if "Timeout" in name else f"failed ({name})"
                return LiveResult("error", f"page load {reason}")
            finally:
                await page.close()
