"""Dodatni kanali obaveštenja (spec. §16.6): Telegram bot, Pushover, webhook. Svaki se uključuje zasebno
i ima probno slanje. Tokeni i tajne se čuvaju šifrovano.
"""

import asyncio
import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .. import crypto

CHANNELS = "notify.channels"
DEFAULTS: dict[str, Any] = {
    "telegram": {"enabled": False, "bot_token_enc": None, "chat_id": "", "min_severity": "high"},
    "pushover": {"enabled": False, "app_token_enc": None, "user_key_enc": None, "min_severity": "high"},
    "webhook": {"enabled": False, "url": "", "secret_enc": None, "min_severity": "warning"},
}
SECRETS = {"telegram": ["bot_token"], "pushover": ["app_token", "user_key"], "webhook": ["secret"]}
SEVERITY_PRIORITY = {"info": -1, "warning": 0, "high": 1, "critical": 1}  # Pushover prioritet


class ChannelError(Exception):
    pass


def merged(stored: dict[str, Any] | None) -> dict[str, Any]:
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    for name, cfg in (stored or {}).items():
        if name in out and isinstance(cfg, dict):
            out[name].update(cfg)
    return out


def public(cfg: dict[str, Any]) -> dict[str, Any]:
    """Za API: bez tajni, samo da li su postavljene."""
    out = {}
    for name, c in cfg.items():
        item = {k: v for k, v in c.items() if not k.endswith("_enc")}
        for secret in SECRETS[name]:
            item[f"has_{secret}"] = bool(c.get(f"{secret}_enc"))
        out[name] = item
    return out


def _secret(c: dict[str, Any], name: str) -> str:
    enc = c.get(f"{name}_enc")
    return crypto.decrypt(enc) if enc else ""


def _post(url: str, data: bytes, headers: dict[str, str], timeout: int = 15) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 – URL je iz podešavanja administratora
            if resp.status >= 300:
                raise ChannelError(f"Server je vratio {resp.status}.")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:200]
        raise ChannelError(f"Server je vratio {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ChannelError(f"Slanje nije uspelo: {getattr(exc, 'reason', exc)}") from exc


def _send_sync(name: str, c: dict[str, Any], title: str, body: str, url: str | None, severity: str,
               payload: dict[str, Any] | None) -> None:
    if name == "telegram":
        token, chat = _secret(c, "bot_token"), str(c.get("chat_id") or "").strip()
        if not token or not chat:
            raise ChannelError("Telegram: potrebni su token bota i chat ID.")
        text = f"*{_md(title)}*\n{_md(body)}" + (f"\n{url}" if url else "")
        data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "Markdown",
                                       "disable_web_page_preview": "true"}).encode()
        _post(f"https://api.telegram.org/bot{token}/sendMessage", data, {"Content-Type": "application/x-www-form-urlencoded"})
    elif name == "pushover":
        app, user = _secret(c, "app_token"), _secret(c, "user_key")
        if not app or not user:
            raise ChannelError("Pushover: potrebni su API token aplikacije i korisnički ključ.")
        fields = {"token": app, "user": user, "title": title[:250], "message": body[:1000],
                  "priority": str(SEVERITY_PRIORITY.get(severity, 0))}
        if url:
            fields.update({"url": url, "url_title": "Otvori alarm"})
        _post("https://api.pushover.net/1/messages.json", urllib.parse.urlencode(fields).encode(),
              {"Content-Type": "application/x-www-form-urlencoded"})
    elif name == "webhook":
        target = str(c.get("url") or "").strip()
        if not target.startswith(("http://", "https://")):
            raise ChannelError("Webhook: unesite ispravnu http(s) adresu.")
        data = json.dumps(payload or {"title": title, "message": body, "severity": severity, "url": url},
                          ensure_ascii=False, default=str).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "SmartDisk"}
        secret = _secret(c, "secret")
        if secret:
            headers["X-SmartDisk-Signature"] = "sha256=" + hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
        _post(target, data, headers)
    else:
        raise ChannelError("Nepoznat kanal.")


def _md(text: str) -> str:
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


async def send(name: str, c: dict[str, Any], title: str, body: str, url: str | None, severity: str,
               payload: dict[str, Any] | None = None) -> None:
    await asyncio.to_thread(_send_sync, name, c, title, body, url, severity, payload)
