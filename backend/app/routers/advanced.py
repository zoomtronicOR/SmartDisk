"""Faza 5: prognoze, dodatni kanali, režim održavanja, zakazani izveštaji, backup."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import analytics, backup, crypto, reports, schedules
from ..audit import audit
from ..db import get_db
from ..deps import admin_only, current_user
from ..health import SEVERITIES
from ..models import Device, Disk, StoragePool, User, utcnow
from ..notify import channels, config

router = APIRouter(prefix="/api", tags=["advanced"])


# --- Prognoze ---


@router.get("/predictions")
async def get_predictions(days: int = 90, _: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Procene trenda (spec. §16.1). Nisu dijagnoza: svaka stavka nosi kvalitet podataka."""
    days = max(7, min(days, 365))
    data = await analytics.predictions(db, days)
    disk_ids = {r["disk_id"] for r in data["disks"]}
    pool_ids = {r["pool_id"] for r in data["pools"]}
    disks = {d.id: (d, dev) for d, dev in (await db.execute(
        select(Disk, Device).join(Device, Device.id == Disk.device_id).where(Disk.id.in_(disk_ids), Device.deleted_at.is_(None))
    )).all()} if disk_ids else {}
    pools = {p.id: (p, dev) for p, dev in (await db.execute(
        select(StoragePool, Device).join(Device, Device.id == StoragePool.device_id)
        .where(StoragePool.id.in_(pool_ids), Device.deleted_at.is_(None))
    )).all()} if pool_ids else {}
    for r in data["disks"]:
        if r["disk_id"] in disks:
            d, dev = disks[r["disk_id"]]
            r["disk_label"] = f"{dev.name} · {d.device_path} · {d.model or '?'}"
    data["disks"] = [r for r in data["disks"] if "disk_label" in r]
    for r in data["pools"]:
        if r["pool_id"] in pools:
            p, dev = pools[r["pool_id"]]
            r.update(pool_label=f"{dev.name} · {p.name}", technology=p.technology, used_bytes=p.used_bytes,
                     capacity_bytes=p.capacity_bytes, free_bytes=p.free_bytes)
            r["days_to_full"] = (p.free_bytes / r["slope_bytes_per_day"]) if p.free_bytes and r["slope_bytes_per_day"] > 0 else None
    data["pools"] = [r for r in data["pools"] if "pool_label" in r]
    data["note"] = ("Procene se računaju linearnim trendom iz istorije i nisu dijagnoza. SMART podaci ne mogu "
                    "garantovati predviđanje otkaza; kvalitet procene zavisi od količine i ujednačenosti podataka.")
    return data


# --- Dodatni kanali ---


class ChannelIn(BaseModel):
    enabled: bool = False
    min_severity: str = "high"
    chat_id: str | None = Field(None, max_length=64)
    url: str | None = Field(None, max_length=500)
    bot_token: str | None = Field(None, max_length=200)  # None = ne menja; "" = briše
    app_token: str | None = Field(None, max_length=200)
    user_key: str | None = Field(None, max_length=200)
    secret: str | None = Field(None, max_length=200)

    @field_validator("min_severity")
    @classmethod
    def check_severity(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError("Nepoznat nivo ozbiljnosti.")
        return v

    @field_validator("url")
    @classmethod
    def check_url(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("Adresa mora počinjati sa http:// ili https://.")
        return v


def _apply(old: dict[str, Any], name: str, body: ChannelIn) -> dict[str, Any]:
    new = dict(old)
    new["enabled"], new["min_severity"] = body.enabled, body.min_severity
    if name == "telegram":
        new["chat_id"] = (body.chat_id or "").strip()
    if name == "webhook":
        new["url"] = (body.url or "").strip()
    for secret in channels.SECRETS[name]:
        value = getattr(body, secret)
        if value == "":
            new[f"{secret}_enc"] = None
        elif value:
            new[f"{secret}_enc"] = crypto.encrypt(value.strip())
    return new


@router.get("/notifications/channels")
async def get_channels(_: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return channels.public(channels.merged(await config.load_raw(db, channels.CHANNELS)))


@router.put("/notifications/channels/{name}")
async def put_channel(name: str, body: ChannelIn, request: Request, admin: User = Depends(admin_only),
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if name not in channels.DEFAULTS:
        raise HTTPException(404, "Nepoznat kanal.")
    all_cfg = channels.merged(await config.load_raw(db, channels.CHANNELS))
    all_cfg[name] = _apply(all_cfg[name], name, body)
    await config.save(db, channels.CHANNELS, all_cfg, admin.username)
    audit(db, request, admin, "settings.channel_updated", "settings", name, {"enabled": body.enabled})
    await db.commit()
    return channels.public(all_cfg)[name]


@router.post("/notifications/channels/{name}/test")
async def test_channel(name: str, body: ChannelIn, _: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    if name not in channels.DEFAULTS:
        raise HTTPException(404, "Nepoznat kanal.")
    cfg = _apply(channels.merged(await config.load_raw(db, channels.CHANNELS))[name], name, body)
    general = await config.load(db, config.GENERAL)
    try:
        await channels.send(name, cfg, "SmartDisk – probna poruka", "Ovaj kanal obaveštenja radi.",
                            (general.get("base_url") or None), "info", {"test": True, "title": "SmartDisk – probna poruka"})
    except channels.ChannelError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"message": "Probna poruka je poslata."}


# --- Režim održavanja ---


class MaintenanceIn(BaseModel):
    until: datetime | None = None
    note: str = Field("", max_length=300)


@router.put("/notifications/maintenance")
async def put_maintenance(body: MaintenanceIn, request: Request, admin: User = Depends(admin_only),
                          db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    general = await config.load(db, config.GENERAL)
    if body.until is not None and body.until <= utcnow():
        raise HTTPException(422, "Kraj održavanja mora biti u budućnosti.")
    general["maintenance_until"] = body.until.isoformat() if body.until else None
    general["maintenance_note"] = body.note
    await config.save(db, config.GENERAL, general, admin.username)
    audit(db, request, admin, "settings.maintenance", "settings", "maintenance",
          {"until": general["maintenance_until"], "note": body.note})
    await db.commit()
    return general


# --- Zakazani izveštaji ---


class ScheduleIn(BaseModel):
    id: str | None = None
    enabled: bool = True
    name: str = Field(..., min_length=1, max_length=100)
    kinds: list[str] = Field(..., min_length=1)
    period: str = Field("weekly", pattern=r"^(daily|weekly|monthly)$")
    hour: int = Field(7, ge=0, le=23)
    weekday: int = Field(1, ge=1, le=7)
    format: str = Field("pdf", pattern=r"^(pdf|xlsx|csv)$")
    recipients: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("kinds")
    @classmethod
    def check_kinds(cls, v: list[str]) -> list[str]:
        bad = [k for k in v if k not in reports.REPORT_KINDS]
        if bad:
            raise ValueError(f"Nepoznat izveštaj: {', '.join(bad)}")
        return v

    @field_validator("recipients")
    @classmethod
    def check_recipients(cls, v: list[str]) -> list[str]:
        out = [r.strip() for r in v if r.strip()]
        for r in out:
            if "@" not in r or " " in r:
                raise ValueError(f"Neispravna e-adresa: {r}")
        return out


async def _schedules(db: AsyncSession) -> list[dict[str, Any]]:
    return (await config.load_raw(db, schedules.KEY) or {}).get("items", [])


@router.get("/report-schedules")
async def list_schedules(_: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await _schedules(db)


@router.put("/report-schedules")
async def save_schedule(body: ScheduleIn, request: Request, admin: User = Depends(admin_only),
                        db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    items = await _schedules(db)
    data = body.model_dump()
    existing = next((i for i in items if i.get("id") == body.id), None) if body.id else None
    if existing:
        data["last_sent_at"], data["last_status"] = existing.get("last_sent_at"), existing.get("last_status")
        items = [data if i.get("id") == body.id else i for i in items]
    else:
        data["id"] = schedules.new_id()
        items.append(data)
    await config.save(db, schedules.KEY, {"items": items}, admin.username)
    audit(db, request, admin, "settings.report_schedule_saved", "settings", data["id"], {"name": data["name"]})
    await db.commit()
    return items


@router.delete("/report-schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, request: Request, admin: User = Depends(admin_only),
                          db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    items = [i for i in await _schedules(db) if i.get("id") != schedule_id]
    await config.save(db, schedules.KEY, {"items": items}, admin.username)
    audit(db, request, admin, "settings.report_schedule_deleted", "settings", schedule_id, None)
    await db.commit()
    return items


@router.post("/report-schedules/{schedule_id}/send")
async def send_schedule(schedule_id: str, _: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    item = next((i for i in await _schedules(db) if i.get("id") == schedule_id), None)
    if item is None:
        raise HTTPException(404, "Raspored nije pronađen.")
    try:
        return {"message": await schedules.send(item)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# --- Backup ---

BACKUP_KEY = "backup.settings"
BACKUP_DEFAULTS = {"enabled": True, "hour": 2, "keep": 14, "last": None}


async def backup_settings(db: AsyncSession) -> dict[str, Any]:
    return {**BACKUP_DEFAULTS, **(await config.load_raw(db, BACKUP_KEY) or {})}


class BackupSettingsIn(BaseModel):
    enabled: bool = True
    hour: int = Field(2, ge=0, le=23)
    keep: int = Field(14, ge=1, le=365)


@router.get("/backups")
async def get_backups(_: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {"settings": await backup_settings(db), "files": backup.list_backups(), "directory": str(backup.BACKUP_DIR)}


@router.put("/backups/settings")
async def put_backup_settings(body: BackupSettingsIn, request: Request, admin: User = Depends(admin_only),
                              db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    cfg = await backup_settings(db)
    cfg.update(body.model_dump())
    await config.save(db, BACKUP_KEY, cfg, admin.username)
    audit(db, request, admin, "settings.backup_updated", "settings", "backup", body.model_dump())
    await db.commit()
    return cfg


async def run_backup(username: str) -> dict[str, Any]:
    from ..db import SessionLocal

    async with SessionLocal() as db:
        cfg = await backup_settings(db)
    try:
        info = await backup.create(int(cfg["keep"]))
    except backup.BackupError as exc:
        info = {"status": "failed", "error": str(exc), "finished_at": utcnow()}
    async with SessionLocal() as db:
        cfg = await backup_settings(db)
        cfg["last"] = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in info.items()}
        await config.save(db, BACKUP_KEY, cfg, username)
        await db.commit()
    return info


@router.post("/backups")
async def create_backup(request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    info = await run_backup(admin.username)
    audit(db, request, admin, "backup.created", "backup", info.get("file"), {"status": info["status"]})
    await db.commit()
    if info["status"] != "ok":
        raise HTTPException(500, info["error"])
    return info
