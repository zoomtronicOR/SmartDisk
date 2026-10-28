"""Podešavanja, pregled (dashboard), audit log, zdravlje aplikacije."""

import shutil
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import false, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import __version__, scheduler, settings_store
from ..audit import audit
from ..constants import PLATFORMS, ROLES
from ..db import get_db
from ..deps import admin_only, current_user
from ..health import HEALTH_LEVELS, SEVERITIES
from ..models import AuditLog, CollectionRun, Device, Disk, DiskSample, Event, StoragePool, User
from ..schemas import AuditOut, AuditPage, CollectionSettings, CollectionSettingsIn, GeneralSettings, RunOut
from .devices import device_status
from .storage import disk_findings, last_smart_samples, standby_ids

router = APIRouter(prefix="/api", tags=["system"])

# Privremeni prag za „povišenu temperaturu” na pregledu; podesivi pragovi po tipu diska dolaze u Fazi 4.
HOT_TEMPERATURE_C = 50


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Javni health-check (bez detalja), za nadzor servisa."""
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    scheduler_ok = scheduler.scheduler_healthy()
    return {"status": "ok" if db_ok and scheduler_ok else "degraded", "database": db_ok, "scheduler": scheduler_ok}


@router.get("/meta")
async def meta(_: User = Depends(current_user)) -> dict[str, Any]:
    return {"version": __version__, "platforms": PLATFORMS, "roles": ROLES}


@router.get("/system/status")
async def system_status(_: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    db_size = await db.scalar(text("SELECT pg_database_size(current_database())"))
    disk = shutil.disk_usage("/")
    last_success = await db.scalar(
        select(func.max(CollectionRun.finished_at)).where(CollectionRun.status.in_(("success", "partial")))
    )
    return {
        "version": __version__,
        "scheduler_running": scheduler.scheduler_healthy(),
        "scheduler_heartbeat_at": scheduler.last_heartbeat(),
        "collection_jobs": scheduler.job_count(),
        "database_ok": True,
        "database_size_bytes": db_size,
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
        "last_successful_collection_at": last_success,
    }


@router.get("/dashboard/summary")
async def dashboard_summary(_: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    devices = list(await db.scalars(select(Device).where(Device.deleted_at.is_(None))))
    counts = {"not_configured": 0, "disabled": 0, "waiting": 0, "ok": 0, "error": 0}
    for device in devices:
        counts[device_status(device)] += 1

    next_runs = [t for d in devices if (t := scheduler.next_run_at(d.id)) is not None]
    names = {d.id: d.name for d in devices}
    recent = await db.scalars(
        select(CollectionRun).where(CollectionRun.device_id.in_(list(names)) if names else false())
        .order_by(CollectionRun.started_at.desc()).limit(10)
    )
    recent_runs = []
    for run in recent:
        out = RunOut.model_validate(run)
        out.device_name = names.get(run.device_id)
        recent_runs.append(out)
    last_finished: datetime | None = max((r.finished_at for r in recent_runs if r.finished_at), default=None)

    disk_counts = {"ok": 0, "warning": 0, "critical": 0, "unknown": 0}
    attention: list[dict[str, Any]] = []
    disk_rows = (await db.execute(
        select(Disk, DiskSample).outerjoin(DiskSample, DiskSample.id == Disk.latest_sample_id)
        .where(Disk.device_id.in_(list(names)) if names else false())
    )).all()
    temps = []
    last = await last_smart_samples(db, standby_ids(list(disk_rows)))
    smart_failed = hot = 0
    for disk, sample in disk_rows:
        state, reasons = disk_findings(sample, disk.is_present, last.get(disk.id))
        disk_counts[state] += 1
        effective = last.get(disk.id) or sample
        if effective is not None and disk.is_present:
            if effective.temperature_c is not None:
                temps.append(effective.temperature_c)
                hot += effective.temperature_c >= HOT_TEMPERATURE_C
            smart_failed += effective.smart_health == "failed"
        if state in ("critical", "warning") or not disk.is_present:
            attention.append({"kind": "disk", "id": disk.id, "device_name": names.get(disk.device_id),
                              "name": f"{disk.device_path} · {disk.model or '?'}", "state": state, "reasons": reasons})
    pools = list(await db.scalars(
        select(StoragePool).where(StoragePool.device_id.in_(list(names)) if names else false(),
                                  StoragePool.is_present.is_(True))
    ))
    for pool in pools:
        if pool.healthy is False:
            attention.append({"kind": "pool", "id": pool.id, "device_name": names.get(pool.device_id),
                              "name": pool.name, "state": "critical",
                              "reasons": [f"Stanje: {pool.status}"] + ([pool.message] if pool.message else [])})
    health_counts = {lvl: 0 for lvl in HEALTH_LEVELS}
    for disk, _ in disk_rows:
        health_counts[disk.health_level if disk.health_level in health_counts else "unknown"] += 1
    alarm_rows = (await db.execute(
        select(Event.severity, func.count()).where(Event.status.in_(("open", "acknowledged")))
        .group_by(Event.severity)
    )).all()
    recent_events = list(await db.scalars(
        select(Event).where(Event.status != "pending").order_by(Event.last_seen_at.desc()).limit(8)
    ))
    return {
        "health": health_counts,
        "alarms": {sev: 0 for sev in SEVERITIES} | {sev: n for sev, n in alarm_rows},
        "recent_events": [{"id": e.id, "severity": e.severity, "status": e.status, "title": e.title,
                           "last_seen_at": e.last_seen_at, "first_seen_at": e.first_seen_at} for e in recent_events],
        "disks_total": len(disk_rows),
        "disks_by_state": disk_counts,
        "pools_total": len(pools),
        "pools_problem": sum(1 for p in pools if p.healthy is False),
        "pools_scanning": sum(1 for p in pools if p.scan_state == "in_progress"),
        "max_temperature_c": max(temps, default=None),
        "smart_failed_disks": smart_failed,
        "hot_disks": hot,
        "hot_threshold_c": HOT_TEMPERATURE_C,
        "attention": sorted(attention, key=lambda a: a["state"] != "critical"),
        "devices_total": len(devices),
        "devices_by_status": counts,
        "last_collection_at": last_finished,
        "next_collection_at": min(next_runs) if next_runs else None,
        "recent_runs": recent_runs,
        "scheduler_running": scheduler.scheduler_healthy(),
    }


@router.get("/settings/collection", response_model=CollectionSettings)
async def get_collection_settings(
    _: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> CollectionSettings:
    return CollectionSettings(
        default_interval_minutes=await settings_store.get_setting(db, settings_store.DEFAULT_INTERVAL),
        raw_retention_days=await settings_store.get_setting(db, settings_store.RAW_RETENTION_DAYS),
    )


@router.put("/settings/collection", response_model=CollectionSettings)
async def put_collection_settings(
    body: CollectionSettingsIn, request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)
) -> CollectionSettings:
    old = await settings_store.get_setting(db, settings_store.DEFAULT_INTERVAL)
    old_retention = await settings_store.get_setting(db, settings_store.RAW_RETENTION_DAYS)
    retention = body.raw_retention_days or old_retention
    await settings_store.set_setting(db, settings_store.DEFAULT_INTERVAL, body.default_interval_minutes, admin.username)
    await settings_store.set_setting(db, settings_store.RAW_RETENTION_DAYS, retention, admin.username)
    changes: dict[str, Any] = {}
    if old != body.default_interval_minutes:
        changes["default_interval_minutes"] = {"from": old, "to": body.default_interval_minutes}
    if old_retention != retention:
        changes["raw_retention_days"] = {"from": old_retention, "to": retention}
    audit(db, request, admin, "settings.collection_updated", "settings", "collection", changes)
    await db.commit()
    await scheduler.sync_all()
    return CollectionSettings(default_interval_minutes=body.default_interval_minutes, raw_retention_days=retention)


@router.get("/settings/general", response_model=GeneralSettings)
async def get_general_settings(_: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> GeneralSettings:
    return GeneralSettings(timezone=await settings_store.get_setting(db, settings_store.TIMEZONE))


@router.put("/settings/general", response_model=GeneralSettings)
async def put_general_settings(
    body: GeneralSettings, request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)
) -> GeneralSettings:
    await settings_store.set_setting(db, settings_store.TIMEZONE, body.timezone, admin.username)
    audit(db, request, admin, "settings.general_updated", "settings", "general", {"timezone": body.timezone})
    await db.commit()
    return body


@router.get("/audit", response_model=AuditPage)
async def audit_log(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, max_length=64),
    _: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> AuditPage:
    query = select(AuditLog)
    count_query = select(func.count()).select_from(AuditLog)
    if action:
        query = query.where(AuditLog.action.startswith(action))
        count_query = count_query.where(AuditLog.action.startswith(action))
    total = await db.scalar(count_query) or 0
    rows = await db.scalars(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).offset(offset))
    return AuditPage(items=[AuditOut.model_validate(r) for r in rows], total=total)
