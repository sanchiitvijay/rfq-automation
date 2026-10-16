"""Sending the reviewed RFQ to the point of contact. Only ever triggered by a person clicking Send."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from email_validator import EmailNotValidError, validate_email

from backend.app.settings import Settings
from rfq.models import Sheet
from rfq.reply import build_reply


class RecipientRejected(ValueError):
    pass


class PermanentSendError(RuntimeError):
    """Retrying will not help (bad credentials, recipient refused)."""


def check_recipient(address: str, allowed_domains: list[str]) -> str:
    try:
        normalized = validate_email(address, check_deliverability=False).normalized
    except EmailNotValidError as e:
        raise RecipientRejected(str(e)) from e
    domain = normalized.rsplit("@", 1)[-1].lower()
    if allowed_domains and domain not in allowed_domains:
        raise RecipientRejected(f"{domain} is not an allowed recipient domain ({', '.join(allowed_domains)})")
    return normalized


def build_message(settings: Settings, sheet: Sheet, xlsx: Path, *, to: str, cc: list[str], subject: str, body: str,
                  in_reply_to: str = "", version: int = 1) -> EmailMessage:
    msg = build_reply(sheet, None, xlsx, subject=subject, to=to, body=body,
                      filename="RFQ.xlsx" if version <= 1 else f"RFQ_v{version}.xlsx")
    msg["From"] = settings.bot_email
    if cc:
        msg["Cc"] = ", ".join(cc)
    if in_reply_to:  # keep the reply in the original thread
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg["Message-ID"] = make_msgid(domain=(settings.bot_email.split("@")[-1] or "rfq.local"))
    msg["Auto-Submitted"] = "auto-replied"
    return msg


def smtp_send(settings: Settings, msg: EmailMessage) -> str:
    if not settings.bot_email:
        raise PermanentSendError("BOT_EMAIL is not set in .env")
    try:
        if settings.smtp_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30,
                                                    context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
        with server:
            if settings.smtp_starttls:
                server.starttls(context=ssl.create_default_context())
            if settings.bot_password:
                server.login(settings.bot_email, settings.bot_password.replace(" ", ""))
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise PermanentSendError("Gmail login failed: check BOT_EMAIL and BOT_PASSWORD (App Password)") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise PermanentSendError(f"recipient refused by the mail server: {list(e.recipients)}") from e
    return str(msg["Message-ID"])
