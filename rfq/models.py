"""Data shapes passed between the steps. All are plain dataclasses that round-trip through JSON,
so the backend can store a sheet in Postgres and regenerate the Excel from it at any time."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from rfq.config import SPEC_COLUMNS, STATUS_NOT_FOUND

ItemKind = Literal["ferguson", "competitor"]
LookupSource = Literal["live", "cache", "catalog", "serpapi", "serpapi+catalog", "manual", "none"]
FlagType = Literal["missing", "suspicious", "not_found"]
CheckKind = Literal["code", "llm"]


@dataclass
class RequestItem:
    """One product the email asks for, in the order it first appears."""

    position: int
    raw_token: str  # exactly as written in the email, e.g. "#5106926" or "17783-79-3000"
    product_id: str  # Ferguson ID, or the competitor code itself
    kind: ItemKind
    context: str = ""  # the line it was found on
    origin: str = "body"  # "body" or "attachment:<file>"
    qty: str | None = None
    brand: str | None = None
    occurrences: int = 1


@dataclass
class Cell:
    """A filled value and where it came from. A blank value is never stored as a Cell."""

    value: str
    source_type: str
    confidence: str
    source: str
    url: str = ""  # the page or document the value was read from ("" for rules and human edits)


@dataclass
class Row:
    product_id: str
    kind: ItemKind
    lookup_status: str = STATUS_NOT_FOUND
    lookup_source: LookupSource = "none"
    raw_token: str = ""
    context: str = ""
    qty: str | None = None
    tried: list[str] = field(default_factory=list)  # e.g. ["live: not on ferguson.com", "catalog: not listed"]
    not_found_reason: str = ""
    cells: dict[str, Cell] = field(default_factory=dict)
    supplier: dict[str, Cell] = field(default_factory=dict)  # Supplier sheet: brand, part numbers, price…

    def value(self, column: str) -> str:
        cell = self.cells.get(column)
        return cell.value if cell else ""

    def missing_columns(self) -> list[str]:
        return [c for c in SPEC_COLUMNS if not self.value(c)]


@dataclass
class Note:
    product_id: str
    note: str


@dataclass
class Sheet:
    """The whole RFQ: rows in request order plus notes and run-level warnings."""

    rows: list[Row] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mode: str = "live"  # "live" or "offline"

    def add_note(self, product_id: str, note: str) -> None:
        if not any(n.product_id == product_id and n.note == note for n in self.notes):
            self.notes.append(Note(product_id, note))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Sheet:
        rows = []
        for r in data.get("rows", []):
            r = dict(r)
            r["cells"] = {k: Cell(**v) for k, v in r.get("cells", {}).items()}
            r["supplier"] = {k: Cell(**v) for k, v in r.get("supplier", {}).items()}
            old_extra = r.pop("extra", None) or {}  # stored by an earlier version: plain strings, no source
            for k, v in old_extra.items():
                r["supplier"].setdefault(k, Cell(str(v), "earlier_run", "low", "recorded by an earlier version"))
            rows.append(Row(**r))
        return cls(
            rows=rows,
            notes=[Note(**n) for n in data.get("notes", [])],
            warnings=list(data.get("warnings", [])),
            mode=data.get("mode", "live"),
        )


@dataclass
class Flag:
    cell: str  # Excel reference on the RFQ sheet, e.g. "S7"
    product_id: str
    column: str
    type: FlagType
    check: CheckKind
    reason: str


@dataclass
class QualityReport:
    flags: list[Flag] = field(default_factory=list)
    fill_overall: float = 0.0  # all requested rows
    fill_found: float = 0.0  # found rows only
    fill_by_column: dict[str, float] = field(default_factory=dict)
    fill_by_product: dict[str, float] = field(default_factory=dict)
    llm_status: str = "not run"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QualityReport:
        data = dict(data)
        data["flags"] = [Flag(**f) for f in data.get("flags", [])]
        return cls(**data)


@dataclass
class ParsedEmail:
    subject: str = ""
    sender: str = ""
    date: str = ""
    message_id: str = ""
    body: str = ""
    attachments: list[tuple[str, bytes]] = field(default_factory=list)  # (filename, bytes)
    warnings: list[str] = field(default_factory=list)
