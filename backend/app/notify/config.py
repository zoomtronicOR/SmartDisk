"""Podešavanja kanala obaveštenja (čuvaju se u app_settings; lozinke šifrovane, nikad se ne vraćaju kroz API)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto, settings_store

EMAIL = "notify.email"
MQTT = "notify.mqtt"
PUSH_KEYS = "notify.push_keys"
GENERAL = "notify.general"
THRESHOLDS = "alarms.thresholds"

DEFAULTS: dict[str, dict[str, Any]] = {
    EMAIL: {
        "enabled": False,
        "host": "",
        "port": 587,
        "security": "starttls",  # starttls / ssl / none
        "username": "",
        "password_enc": None,
        "from_addr": "",
        "recipients": [],
        "min_severity": "high",
        "timeout": 20,
    },
    MQTT: {
        "enabled": False,
        "host": "",
        "port": 1883,
        "tls": False,
        "tls_insecure": False,
        "username": "",
        "password_enc": None,
        "client_id": "smartdisk",
        "prefix": "diskmonitor",
        "qos": 1,
        "retain": True,
        "heartbeat_seconds": 60,
        "discovery": True,
        "discovery_prefix": "homeassistant",
        "entities": ["summary", "device_status", "disk_temperature", "disk_smart", "disk_health", "disk_poh",
                     "disk_wear", "pool_status", "pool_errors"],
    },
    GENERAL: {
        "base_url": "",  # adresa aplikacije za linkove u obaveštenjima, npr. https://192.168.88.246
        "notify_resolved": True,
        # Režim održavanja (spec. §16.4): do ovog trenutka šalju se samo kritična obaveštenja.
        "maintenance_until": None,
        "maintenance_note": "",
    },
}

SECRET_FIELDS = {"password_enc"}


async def load(db: AsyncSession, key: str) -> dict[str, Any]:
    from ..models import AppSetting

    row = await db.get(AppSetting, key)
    data = dict(DEFAULTS.get(key, {}))
    if row is not None and isinstance(row.value, dict):
        data.update(row.value)
    return data


async def save(db: AsyncSession, key: str, data: dict[str, Any], username: str | None) -> None:
    from ..models import AppSetting

    row = await db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=data, updated_by=username))
    else:
        row.value = data
        row.updated_by = username


async def load_raw(db: AsyncSession, key: str) -> dict[str, Any] | None:
    from ..models import AppSetting

    row = await db.get(AppSetting, key)
    return row.value if row is not None and isinstance(row.value, dict) else None


def public(data: dict[str, Any]) -> dict[str, Any]:
    """Za API: bez šifrovanih tajni, samo da li je lozinka postavljena."""
    out = {k: v for k, v in data.items() if k not in SECRET_FIELDS}
    out["has_password"] = bool(data.get("password_enc"))
    return out


def password(data: dict[str, Any]) -> str | None:
    enc = data.get("password_enc")
    return crypto.decrypt(enc) if enc else None


async def thresholds(db: AsyncSession) -> dict[str, Any]:
    from ..health import merge_thresholds
    from ..models import AppSetting

    row = await db.get(AppSetting, THRESHOLDS)
    return merge_thresholds(row.value if row is not None else None)


# settings_store poznaje samo jednostavne vrednosti; ključ za pragove registrujemo da get_setting ne pukne.
settings_store.DEFAULTS.setdefault(THRESHOLDS, {})
