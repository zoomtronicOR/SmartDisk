"""Obaveštenja e-poštom (SMTP). Slanje ide u posebnoj niti da ne blokira scheduler."""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from . import config


class EmailError(Exception):
    pass


def _send_sync(cfg: dict[str, Any], pwd: str | None, subject: str, body: str, recipients: list[str]) -> None:
    msg = EmailMessage()
    msg["From"] = cfg["from_addr"]
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="smartdisk")
    msg.set_content(body)
    timeout = int(cfg.get("timeout") or 20)
    context = ssl.create_default_context()
    try:
        if cfg["security"] == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(cfg["host"], int(cfg["port"]), timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=timeout)
        with server:
            server.ehlo()
            if cfg["security"] == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if cfg.get("username"):
                server.login(cfg["username"], pwd or "")
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailError("SMTP server je odbio korisničko ime ili lozinku.") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise EmailError(f"SMTP server je odbio primaoce: {', '.join(exc.recipients)}.") from exc
    except smtplib.SMTPNotSupportedError as exc:
        raise EmailError("Server ne podržava izabrani način (STARTTLS/prijava). Proverite port i bezbednost veze.") from exc
    except ssl.SSLError as exc:
        raise EmailError(f"TLS greška: {exc.reason or exc}. Proverite port (465 = SSL, 587 = STARTTLS).") from exc
    except (TimeoutError, OSError) as exc:
        raise EmailError(f"SMTP server {cfg['host']}:{cfg['port']} nije dostupan ({exc}).") from exc
    except smtplib.SMTPException as exc:
        raise EmailError(f"SMTP greška: {exc}") from exc


async def send(cfg: dict[str, Any], subject: str, body: str, recipients: list[str] | None = None) -> None:
    if not cfg.get("host") or not cfg.get("from_addr"):
        raise EmailError("SMTP nije podešen (server i adresa pošiljaoca su obavezni).")
    to = recipients or cfg.get("recipients") or []
    if not to:
        raise EmailError("Nema primalaca.")
    await asyncio.to_thread(_send_sync, cfg, config.password(cfg), subject, body, to)
