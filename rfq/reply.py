"""The reply email: a short honest summary with RFQ.xlsx attached. mailbot.py replaces the headers."""
from __future__ import annotations

import email.policy
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

from rfq.config import STATUS_NOT_FOUND
from rfq.models import QualityReport, Sheet

XLSX = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def reply_text(sheet: Sheet, report: QualityReport | None) -> str:
    rows = sheet.rows
    not_found = [r for r in rows if r.lookup_status == STATUS_NOT_FOUND]
    lines = ["Hi,", ""]
    if not rows:
        lines += ["We could not find any product IDs in your request. Please reply with the Ferguson item",
                  "numbers (one per line, or in an Excel attachment) and we will prepare the RFQ.", ""]
    else:
        lines.append(f"Please find the RFQ attached: {len(rows) - len(not_found)} of {len(rows)} products found.")
        if not_found:
            lines.append("")
            lines.append("Not found (left blank on purpose, nothing guessed):")
            for r in not_found:
                lines.append(f"  - {r.product_id}: {r.not_found_reason}")
        if report is not None:
            suspicious = sum(1 for f in report.flags if f.type == "suspicious")
            missing = sum(1 for f in report.flags if f.type == "missing")
            lines += ["", f"Fill rate {report.fill_overall}% ({report.fill_found}% for found products). "
                          f"{suspicious} values flagged for review and {missing} fields missing; "
                          "see the Summary sheet for the full list."]
        lines.append("Supplier details (brand, part numbers, price, stock, product page) are on the Supplier sheet.")
        lines.append("Every value has its source and a link on the Sources sheet.")
        lines.append("")
    lines += ["Regards,", "RFQ Agent"]
    return "\n".join(lines)


def build_reply(sheet: Sheet, report: QualityReport | None, xlsx: Path, subject: str = "",
                to: str = "", body: str | None = None, filename: str = "RFQ.xlsx") -> EmailMessage:
    msg = EmailMessage(policy=email.policy.default)
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject or 'RFQ request'}"
    if to:
        msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body if body is not None else reply_text(sheet, report))
    msg.add_attachment(xlsx.read_bytes(), maintype=XLSX[0], subtype=XLSX[1], filename=filename)
    return msg


def write_reply(sheet: Sheet, report: QualityReport | None, xlsx: Path, out: Path, subject: str = "",
                to: str = "") -> Path:
    out.write_bytes(bytes(build_reply(sheet, report, xlsx, subject, to)))
    return out
