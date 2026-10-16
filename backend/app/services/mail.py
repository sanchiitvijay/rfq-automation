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


def _connect(settings: Settings) -> smtplib.SMTP:
    if settings.smtp_ssl:
        server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30,
                                                context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    server.ehlo()
    if settings.smtp_starttls:
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
    return server


def _login(server: smtplib.SMTP, settings: Settings) -> None:
    """One AUTH attempt only. smtplib's login() tries a second mechanism after a failure, but Gmail
    hangs up after the first 535, so the real reason ("Username and Password not accepted") was
    being replaced by "Connection unexpectedly closed"."""
    password = settings.bot_password.replace(" ", "")  # Google shows App Passwords in groups of 4
    if not password:
        return
    server.user, server.password = settings.bot_email, password
    offered = (server.esmtp_features.get("auth") or "").upper().split()
    mechanism = "PLAIN" if "PLAIN" in offered or not offered else "LOGIN"
    method = server.auth_plain if mechanism == "PLAIN" else server.auth_login
    try:
        server.auth(mechanism, method, initial_response_ok=True)
    except smtplib.SMTPAuthenticationError as e:
        detail = e.smtp_error.decode(errors="replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        hint = (" For Gmail: BOT_PASSWORD must be a 16-letter App Password created for exactly this BOT_EMAIL "
                "account (2-Step Verification on), not the normal password.") if "gmail" in settings.smtp_host else ""
        raise PermanentSendError(f"mail login rejected ({e.smtp_code}): {' '.join(detail.split())[:160]}.{hint}") from e
    except smtplib.SMTPServerDisconnected as e:
        raise PermanentSendError("the mail server closed the connection during login; check BOT_EMAIL, "
                                 "BOT_PASSWORD and SMTP_PORT/SMTP_SSL (Gmail: 465 + SSL, or 587 + STARTTLS)") from e


def check_login(settings: Settings) -> str:
    """Connects and logs in, sends nothing. Used by the 'Test mail settings' check."""
    if not settings.bot_email:
        raise PermanentSendError("BOT_EMAIL is not set in .env")
    try:
        server = _connect(settings)
    except (OSError, smtplib.SMTPException) as e:
        raise PermanentSendError(f"cannot reach {settings.smtp_host}:{settings.smtp_port} ({type(e).__name__})") from e
    with server:
        _login(server, settings)
    return f"login to {settings.smtp_host}:{settings.smtp_port} as {settings.bot_email} works"


def smtp_send(settings: Settings, msg: EmailMessage) -> str:
    if not settings.bot_email:
        raise PermanentSendError("BOT_EMAIL is not set in .env")
    with _connect(settings) as server:
        _login(server, settings)
        try:
            server.send_message(msg)
        except smtplib.SMTPRecipientsRefused as e:
            raise PermanentSendError(f"recipient refused by the mail server: {list(e.recipients)}") from e
        except smtplib.SMTPSenderRefused as e:
            raise PermanentSendError(f"sender refused by the mail server ({e.smtp_code})") from e
    return str(msg["Message-ID"])
