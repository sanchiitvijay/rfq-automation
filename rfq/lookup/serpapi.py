"""SerpApi (Google search) lookup: the first stop for a Ferguson ID, so ferguson.com itself is hit as
little as possible.

A search for  site:ferguson.com "<id>"  confirms the product is on ferguson.com and gives its page
URL, title and often price/stock from Google's rich snippet. It does NOT give the spec table, so
specs still come from the catalog or, when needed, from the product page (see resolve.py).

When no key is configured, or the plan's searches are used up (HTTP 429 / "run out of searches"),
SerpApi is switched off for an hour and the flow falls back to reading ferguson.com directly.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

import httpx

from rfq.lookup.cache import Cache
from rfq.models import Cell

log = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search.json"
EXHAUSTED_FLAG = "serpapi:exhausted"
EXHAUSTED_COOLDOWN = 3600
RESULT_TTL = 24 * 3600
_EXHAUSTED_WORDS = ("run out of searches", "plan's limit", "plan limit", "searches per month", "exceeded",
                    "rate limit", "too many requests", "upgrade your plan")
_NO_RESULTS = ("hasn't returned any results", "no results")

Status = Literal["found", "no_result", "exhausted", "error", "disabled"]


@dataclass
class SerpResult:
    status: Status
    reason: str = ""
    url: str = ""
    title: str = ""
    title_truncated: bool = False
    supplier: dict[str, Cell] = field(default_factory=dict)
    from_cache: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SerpResult:
        data = dict(data)
        data["supplier"] = {k: Cell(**v) for k, v in data.get("supplier", {}).items()}
        return cls(**data)


def _clean_title(title: str) -> tuple[str, bool]:
    title = re.sub(r"\s*[|\-–]\s*Ferguson(?:\.com)?\s*$", "", title.strip())
    truncated = title.endswith(("...", "…"))
    return title.rstrip(".… ").strip() if truncated else title, truncated


def parse_response(data: dict[str, Any], pid: str, read_on: str | None = None) -> SerpResult:
    """Pure parser for a SerpApi Google response (tested against saved fixtures)."""
    error = str(data.get("error") or "")
    if error:
        low = error.lower()
        if any(w in low for w in _NO_RESULTS):
            return SerpResult("no_result", "Google has no ferguson.com result for this ID")
        if any(w in low for w in _EXHAUSTED_WORDS):
            return SerpResult("exhausted", f"SerpApi quota used up ({error[:80]})")
        if "api key" in low or "invalid" in low:
            return SerpResult("exhausted", f"SerpApi key rejected ({error[:80]})")
        return SerpResult("error", f"SerpApi error: {error[:120]}")

    pattern = re.compile(rf"^https?://(?:www\.)?ferguson\.com/product/[^?#]*/{re.escape(pid)}\.html", re.I)
    for result in data.get("organic_results") or []:
        link = str(result.get("link") or "")
        if not pattern.match(link):
            continue  # another product, a category page or another site: never trust it
        url = link.split("?")[0].split("#")[0]
        title, truncated = _clean_title(str(result.get("title") or ""))
        read_on = read_on or date.today().isoformat()
        src = f"Google result for the ferguson.com product page (via SerpApi), {read_on}"
        supplier = {
            "Supplier": Cell("Ferguson", "serpapi", "high", src, url),
            "Product page": Cell(url, "serpapi", "high", src, url),
        }
        rich = result.get("rich_snippet") or {}
        exts: list[str] = []
        detected: dict[str, Any] = {}
        for part in ("top", "bottom"):
            block = rich.get(part) or {}
            exts += [str(e) for e in block.get("extensions") or []]
            detected.update(block.get("detected_extensions") or {})
        price = detected.get("price")
        if price is None:
            m = next((re.search(r"\$\s?([\d,]+\.\d{2})", e) for e in exts if "$" in e), None)
            price = m.group(1).replace(",", "") if m else None
        if price is not None:
            supplier["Price (USD)"] = Cell(f"{float(price):.2f}", "serpapi", "medium",
                                           src + " (Google snippet; may lag the live page)", url)
        stock = next((e for e in exts if re.search(r"\b(in stock|out of stock|backorder)", e, re.I)), None)
        if stock:
            supplier["Availability"] = Cell(stock.strip(), "serpapi", "medium", src + " (Google snippet)", url)
        return SerpResult("found", "", url, title, truncated, supplier)
    return SerpResult("no_result", "no Google result points at this product's ferguson.com page")


class SerpApi:
    def __init__(self, key: str, cache: Cache, client: httpx.AsyncClient | None = None,
                 timeout_s: float = 45.0) -> None:
        self.key = key
        self.timeout_s = timeout_s
        self.cache = cache
        self._client = client
        self.calls = 0

    async def enabled(self) -> tuple[bool, str]:
        if not self.key:
            return False, "SERPAPI_API_KEY is not set"
        if await self.cache.has_flag(EXHAUSTED_FLAG):
            return False, "SerpApi quota used up or key rejected earlier (paused for an hour)"
        return True, ""

    async def search(self, pid: str) -> SerpResult:
        cached = await self.cache.get_json(f"serp:{pid}")
        if cached:
            result = SerpResult.from_json(cached)
            result.from_cache = True
            return result
        ok, why = await self.enabled()
        if not ok:
            return SerpResult("disabled", why)
        params = {"engine": "google", "q": f'site:ferguson.com "{pid}"', "num": 10, "hl": "en", "gl": "us",
                  "api_key": self.key}
        client = self._client or httpx.AsyncClient()
        try:
            self.calls += 1
            # a fresh Google search through SerpApi can take 20-60 s; on timeout the page is read instead
            resp = await client.get(SERPAPI_URL, params=params, timeout=self.timeout_s)
            try:
                data = resp.json()
            except ValueError:
                data = {"error": f"HTTP {resp.status_code}"}
            if resp.status_code == 429:
                result = SerpResult("exhausted", "SerpApi quota used up (HTTP 429)")
            elif resp.status_code == 401:
                result = SerpResult("exhausted", "SerpApi key rejected (HTTP 401)")
            else:
                result = parse_response(data, pid)
        except httpx.HTTPError as e:
            slow = isinstance(e, httpx.TimeoutException)
            result = SerpResult("error", f"SerpApi did not answer within {self.timeout_s:.0f} s" if slow
                                else f"SerpApi not reachable ({type(e).__name__})")
        finally:
            if self._client is None:
                await client.aclose()
        if result.status == "exhausted":
            await self.cache.set_flag(EXHAUSTED_FLAG, EXHAUSTED_COOLDOWN)
            log.warning("SerpApi disabled for an hour: %s", result.reason)
        if result.status in ("found", "no_result"):
            await self.cache.set_json(f"serp:{pid}", result.to_json(), RESULT_TTL)
        return result
