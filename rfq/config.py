"""Paths, column layout and environment settings shared by every part of the RFQ flow."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TEMPLATE_PATH = ROOT / "templates" / "rfq_template.xlsx"
CATALOG_JSON = DATA_DIR / "product_catalog.json"
CATALOG_SOURCES_CSV = DATA_DIR / "product_catalog_sources.csv"
SPEC_LINKS_CSV = DATA_DIR / "spec_sheet_links.csv"

# RFQ sheet columns, in template order.
RFQ_COLUMNS: list[str] = [
    "product_id", "Description", "ANSI", "Application", "Color Finish", "Length", "Lettering",
    "Material", "Material Type", "No of Tools", "Temperature Range", "Thickness", "Tool Type",
    "UL Listed", "Width", "OSHA", "Waterworks Application", "Product details", "Weight", "ASTM",
    "Image", "Picture", "Lookup Status",
]
# Columns that hold product values (everything except the key and the status).
SPEC_COLUMNS: list[str] = RFQ_COLUMNS[1:-1]
SOURCES_COLUMNS = ["product_id", "column", "value", "source_type", "confidence", "source", "link"]
# Supplier sheet (who sells it, part numbers, price). Not part of the RFQ template, so it has its own sheet.
SUPPLIER_COLUMNS: list[str] = [
    "Supplier", "Brand", "Manufacturer Part #", "Ferguson Part #", "UPC", "Price (USD)", "Availability",
    "Product page", "Spec sheet",
]
SUPPLIER_PREFIX = "Supplier: "  # how supplier values are named on the Sources sheet
NOTES_COLUMNS = ["product_id", "note"]

STATUS_FOUND = "Found"
STATUS_NOT_FOUND = "Not found"
STATUS_MANUAL = "Manual"

# Input guardrails.
MAX_EML_BYTES = 15 * 1024 * 1024
MAX_BODY_CHARS = 200_000
MAX_IDS = 500
MAX_PDF_BYTES = 20 * 1024 * 1024

# Hosts the flow may contact (besides the LLM API).
ALLOWED_HOSTS = ("www.ferguson.com", "ferguson.com", "api.ferguson.com", "i.ferg-img.com", "serpapi.com")


def load_env(path: Path = ROOT / ".env") -> None:
    """Reads KEY=value lines from .env into the environment (existing variables win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class RunOptions:
    """How one RFQ run behaves."""

    offline: bool = False  # catalog + PDFs only, never opens Chrome
    use_llm: bool = True  # the Quality Agent's contradiction check
    use_pdfs: bool = True
    embed_images: bool = True  # download product thumbnails and put them in the Excel (Image column)
    cdp_url: str = field(default_factory=lambda: os.environ.get("CHROME_CDP_URL", "http://127.0.0.1:9333"))
    openai_model: str = field(default_factory=lambda: os.environ.get("OPENAI_MODEL", "gpt-5-mini"))
    live_timeout_s: float = 20.0
    live_concurrency: int = 2  # ferguson.com tabs at once (also limited globally via Redis)
    # ferguson.com blocks bursts: at most this many page loads per minute, across all workers
    ferguson_rate_per_minute: int = field(default_factory=lambda: _int_env("FERGUSON_RATE_PER_MINUTE", 12))
    serpapi_key: str = field(default_factory=lambda: (os.environ.get("SERPAPI_API_KEY")
                                                      or os.environ.get("SERPAPI_KEY") or "").strip())
    serpapi_timeout_s: float = field(default_factory=lambda: float(_int_env("SERPAPI_TIMEOUT_S", 45)))
    # after a SerpApi hit, open the product page too? "missing" = only when the catalog lacks the product
    scrape_after_serpapi: str = field(default_factory=lambda: os.environ.get("SCRAPE_AFTER_SERPAPI", "missing"))
