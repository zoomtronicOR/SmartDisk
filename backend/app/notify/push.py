"""Web Push (spec. §13): VAPID ključevi se generišu jednom i čuvaju (privatni šifrovan)."""

import asyncio
import base64
import json
import logging
from typing import Any

from cryptography.hazmat.primitives import serialization
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto
from . import config

log = logging.getLogger("smartdisk.push")


async def vapid_keys(db: AsyncSession) -> dict[str, str]:
    """Vraća {public, private_pem}; pri prvom pozivu generiše par i čuva ga (commit radi pozivalac)."""
    data = await config.load(db, config.PUSH_KEYS)
    if data.get("public") and data.get("private_enc"):
        return {"public": data["public"], "private_pem": crypto.decrypt(data["private_enc"])}
    from py_vapid import Vapid01

    vapid = Vapid01()
    vapid.generate_keys()
    private_pem = vapid.private_pem().decode()
    raw = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    public = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    await config.save(db, config.PUSH_KEYS, {"public": public, "private_enc": crypto.encrypt(private_pem)}, "system")
    return {"public": public, "private_pem": private_pem}


class PushGone(Exception):
    """Pretplata više ne postoji (pregledač je povukao dozvolu) - briše se."""


def _send_sync(sub: dict[str, Any], payload: dict[str, Any], private_pem: str, subject: str) -> None:
    from py_vapid import Vapid01
    from pywebpush import WebPushException, webpush

    vapid = Vapid01.from_pem(private_pem.encode())
    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=vapid,
            vapid_claims={"sub": subject},
            ttl=24 * 3600,
            timeout=15,
        )
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            raise PushGone(str(exc)) from exc
        raise


async def send(sub: dict[str, Any], payload: dict[str, Any], private_pem: str, subject: str) -> None:
    await asyncio.to_thread(_send_sync, sub, payload, private_pem, subject)
