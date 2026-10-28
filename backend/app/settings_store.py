"""Podešavanja aplikacije koja se menjaju kroz UI (čuvaju se u tabeli app_settings)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .constants import DEFAULT_TIMEZONE
from .models import AppSetting

DEFAULT_INTERVAL = "collection.default_interval_minutes"
TIMEZONE = "general.timezone"
RAW_RETENTION_DAYS = "retention.raw_days"
NTP_SERVER = "time.ntp_server"

DEFAULTS: dict[str, Any] = {
    DEFAULT_INTERVAL: 15,
    TIMEZONE: DEFAULT_TIMEZONE,
    # Sirova merenja (disk_samples, pool_samples) čuvaju se 12 meseci.
    RAW_RETENTION_DAYS: 365,
    NTP_SERVER: "pool.ntp.org",
}


async def get_setting(db: AsyncSession, key: str) -> Any:
    row = await db.get(AppSetting, key)
    return row.value if row is not None else DEFAULTS[key]


async def set_setting(db: AsyncSession, key: str, value: Any, username: str | None) -> None:
    row = await db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value, updated_by=username))
    else:
        row.value = value
        row.updated_by = username
