"""Turns a raw .eml (or pasted text) into subject, sender, plain-text body and spreadsheet attachments."""
from __future__ import annotations

import email
import email.policy
from email.message import EmailMessage

from bs4 import BeautifulSoup

from rfq.config import MAX_BODY_CHARS, MAX_EML_BYTES
from rfq.models import ParsedEmail

SHEET_EXTENSIONS = (".xlsx", ".xlsm", ".csv", ".xls")


class EmailTooLarge(ValueError):
    pass


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text("\n")
    return "\n".join(line.rstrip() for line in text.splitlines())


def _part_text(part: EmailMessage) -> str:
    try:
        return part.get_content()
    except (LookupError, UnicodeDecodeError):  # unknown or wrong charset
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def parse_eml(raw: bytes) -> ParsedEmail:
    if len(raw) > MAX_EML_BYTES:
        raise EmailTooLarge(f"Email is {len(raw) / 1e6:.1f} MB; the limit is {MAX_EML_BYTES // 1_000_000} MB.")
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    parsed = ParsedEmail(
        subject=str(msg.get("Subject", "") or ""),
        sender=str(msg.get("From", "") or ""),
        date=str(msg.get("Date", "") or ""),
        message_id=str(msg.get("Message-ID", "") or ""),
    )

    plain: list[str] = []
    html: list[str] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if filename or disposition == "attachment":
            name = filename or "attachment"
            if name.lower().endswith(SHEET_EXTENSIONS):
                parsed.attachments.append((name, part.get_payload(decode=True) or b""))
            else:
                parsed.warnings.append(f"Attachment '{name}' ignored (only Excel/CSV attachments are read).")
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            plain.append(_part_text(part))
        elif ctype == "text/html":
            html.append(_part_text(part))

    if plain:
        body = "\n".join(plain)
    elif html:
        body = "\n".join(html_to_text(h) for h in html)
    else:
        body = ""
        if not parsed.attachments:
            parsed.warnings.append("The email has no readable text and no spreadsheet attachment.")
    parsed.body = _limit(body, parsed)
    return parsed


def parse_text(body: str, subject: str = "", sender: str = "") -> ParsedEmail:
    """For pasted email bodies (no attachments possible)."""
    parsed = ParsedEmail(subject=subject, sender=sender)
    parsed.body = _limit(body.replace("\r\n", "\n"), parsed)
    return parsed


def _limit(body: str, parsed: ParsedEmail) -> str:
    if len(body) > MAX_BODY_CHARS:
        parsed.warnings.append(f"Email body cut to the first {MAX_BODY_CHARS:,} characters.")
        return body[:MAX_BODY_CHARS]
    return body
