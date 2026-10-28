"""Diskovi, SMART očitavanja i skladište (pool-ovi). Samo čitanje; podatke upisuje collector."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..adapters import privileges
from ..constants import PLATFORMS
from ..db import get_db
from ..deps import current_user
from ..models import Device, Disk, DiskSample, PoolSample, SmartTest, StoragePool, User

router = APIRouter(prefix="/api", tags=["storage"])

_SAMPLE_COLUMNS = [c.name for c in DiskSample.__table__.columns if c.name not in ("disk_id", "run_id", "attributes")]


async def last_smart_samples(db: AsyncSession, disk_ids: list[int]) -> dict[int, DiskSample]:
    """Poslednje očitavanje sa SMART podacima, za diskove čije je poslednje očitavanje bez njih (npr. standby)."""
    if not disk_ids:
        return {}
    rows = await db.scalars(
        select(DiskSample).distinct(DiskSample.disk_id)
        .where(DiskSample.disk_id.in_(disk_ids), DiskSample.smart_available.is_(True))
        .order_by(DiskSample.disk_id, DiskSample.collected_at.desc())
    )
    return {s.disk_id: s for s in rows}


def standby_ids(pairs: list[tuple[Disk, DiskSample | None]]) -> list[int]:
    return [d.id for d, s in pairs if s is not None and s.smart_health == "standby"]


def disk_findings(sample: DiskSample | None, present: bool, last_smart: DiskSample | None = None) -> tuple[str, list[str]]:
    """Grubo stanje diska za prikaz u Fazi 2 (ocena „Zdravlje diska” dolazi u Fazi 4).

    Vraća (stanje, razlozi): ok / warning / critical / unknown. Nedostatak podataka je uvek „unknown”, nikad „ok”.
    Za disk u standby-ju stanje se procenjuje po poslednjem SMART očitavanju (last_smart), uz napomenu.
    """
    if not present:
        return "unknown", ["Disk nije pronađen u poslednjem ciklusu."]
    if sample is None:
        return "unknown", ["Još nema SMART očitavanja."]
    if sample.smart_health == "failed":
        reasons = ["SMART overall-health: NEUSPEŠNO."]
        if sample.critical_warning:
            reasons.append(f"NVMe critical warning: {sample.critical_warning}.")
        return "critical", reasons
    if sample.smart_health == "standby":
        if last_smart is not None:
            state, reasons = disk_findings(last_smart, True)
            return state, ["Disk je u standby režimu; stanje je po poslednjem SMART očitavanju."] + reasons
        return "unknown", ["Disk je u standby režimu – SMART još nije očitan."]
    if sample.smart_health in ("unavailable", "unknown"):
        return "unknown", [sample.smart_message or "SMART podaci nisu dostupni."]
    reasons = []
    counters = [
        (sample.reallocated_sectors, "realociranih sektora"),
        (sample.pending_sectors, "sektora na čekanju (pending)"),
        (sample.uncorrectable_sectors, "neispravljivih sektora"),
        (sample.media_errors, "NVMe media grešaka"),
    ]
    for value, label in counters:
        if value:
            reasons.append(f"{value} {label}.")
    if sample.available_spare is not None and sample.available_spare_threshold is not None \
            and sample.available_spare <= sample.available_spare_threshold:
        reasons.append("NVMe rezerva je na ili ispod praga.")
    if sample.percentage_used is not None and sample.percentage_used >= 90:
        reasons.append(f"NVMe istrošenost {sample.percentage_used}%.")
    if sample.ssd_life_left is not None and sample.ssd_life_left <= 10:
        reasons.append(f"Preostali vek SSD-a {sample.ssd_life_left}%.")
    return ("warning", reasons) if reasons else ("ok", [])


def sample_dict(sample: DiskSample | None, with_attributes: bool = False) -> dict[str, Any] | None:
    if sample is None:
        return None
    data = {name: getattr(sample, name) for name in _SAMPLE_COLUMNS}
    if with_attributes:
        data["attributes"] = sample.attributes or []
    return data


def disk_dict(disk: Disk, device: Device, sample: DiskSample | None, pools: list[str],
              last_smart: DiskSample | None = None, with_attributes: bool = False) -> dict[str, Any]:
    state, reasons = disk_findings(sample, disk.is_present, last_smart)
    return {
        "id": disk.id,
        "device_id": disk.device_id,
        "device_name": device.name,
        "platform": device.platform,
        "stable_identifier": disk.stable_identifier,
        "device_path": disk.device_path,
        "model": disk.model,
        "vendor": disk.vendor,
        "serial_number": disk.serial_number,
        "wwn": disk.wwn,
        "firmware": disk.firmware,
        "disk_type": disk.disk_type,
        "interface_type": disk.interface_type,
        "capacity_bytes": disk.capacity_bytes,
        "rotation_rate": disk.rotation_rate,
        "form_factor": disk.form_factor,
        "first_seen_at": disk.first_seen_at,
        "last_seen_at": disk.last_seen_at,
        "is_present": disk.is_present,
        "state": state,
        "reasons": reasons,
        "health": {"level": disk.health_level or "unknown", "score": disk.health_score,
                   "reasons": disk.health_reasons or [], "updated_at": disk.health_updated_at},
        "pools": pools,
        "latest": sample_dict(sample, with_attributes),
        # Kada je poslednje očitavanje bez SMART podataka (standby), poslednje očitavanje sa njima.
        "last_smart": sample_dict(last_smart, with_attributes) if last_smart is not None else None,
    }


async def _pool_names_by_disk(db: AsyncSession, device_ids: list[int]) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    pools = await db.scalars(
        select(StoragePool).where(StoragePool.device_id.in_(device_ids), StoragePool.is_present.is_(True))
    )
    for pool in pools:
        for member in pool.members or []:
            disk_id = member.get("disk_id")
            if disk_id and pool.name not in result.setdefault(disk_id, []):
                result[disk_id].append(pool.name)
    return result


@router.get("/disks")
async def list_disks(
    device_id: int | None = None,
    include_missing: bool = True,
    _: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    query = (
        select(Disk, Device, DiskSample)
        .join(Device, Device.id == Disk.device_id)
        .outerjoin(DiskSample, DiskSample.id == Disk.latest_sample_id)
        .where(Device.deleted_at.is_(None))
        .order_by(Device.name, Disk.device_path)
    )
    if device_id is not None:
        query = query.where(Disk.device_id == device_id)
    if not include_missing:
        query = query.where(Disk.is_present.is_(True))
    rows = (await db.execute(query)).all()
    pools = await _pool_names_by_disk(db, list({d.device_id for d, _, _ in rows}))
    last = await last_smart_samples(db, standby_ids([(d, s) for d, _, s in rows]))
    return [disk_dict(disk, device, sample, pools.get(disk.id, []), last.get(disk.id)) for disk, device, sample in rows]


@router.get("/disks/{disk_id}")
async def get_disk(disk_id: int, _: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = (await db.execute(
        select(Disk, Device).join(Device, Device.id == Disk.device_id)
        .where(Disk.id == disk_id, Device.deleted_at.is_(None))
    )).first()
    if row is None:
        raise HTTPException(404, "Disk nije pronađen.")
    disk, device = row
    sample = await db.get(DiskSample, disk.latest_sample_id) if disk.latest_sample_id else None
    pools = await _pool_names_by_disk(db, [device.id])
    last = await last_smart_samples(db, standby_ids([(disk, sample)]))
    data = disk_dict(disk, device, sample, pools.get(disk.id, []), last.get(disk.id), with_attributes=True)
    tests = await db.scalars(
        select(SmartTest).where(SmartTest.disk_id == disk_id).order_by(SmartTest.lifetime_hours.desc()).limit(50)
    )
    data["self_tests"] = [
        {"test_type": t.test_type, "status": t.status, "passed": t.passed,
         "lifetime_hours": t.lifetime_hours if t.lifetime_hours >= 0 else None,
         "remaining_percent": t.remaining_percent, "first_seen_at": t.first_seen_at}
        for t in tests
    ]
    return data


@router.get("/disks/{disk_id}/samples")
async def disk_samples(
    disk_id: int,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(200, ge=1, le=5000),
    _: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(DiskSample).where(DiskSample.disk_id == disk_id)
    if date_from:
        query = query.where(DiskSample.collected_at >= date_from)
    if date_to:
        query = query.where(DiskSample.collected_at <= date_to)
    rows = await db.scalars(query.order_by(DiskSample.collected_at.desc()).limit(limit))
    return [sample_dict(s) for s in rows]


@router.get("/disks/{disk_id}/raw")
async def disk_raw(disk_id: int, _: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Poslednji kompletan izlaz `smartctl` za disk (izvor podataka)."""
    disk = await db.get(Disk, disk_id)
    if disk is None:
        raise HTTPException(404, "Disk nije pronađen.")
    return {"collected_at": disk.last_seen_at, "raw": disk.last_raw}


@router.get("/platforms/{platform}/privileges")
async def platform_privileges(platform: str, _: User = Depends(current_user)) -> dict[str, Any]:
    """Profil privilegija za namenski nalog: tačne sudo komande i gotov sudoers fajl."""
    if platform not in PLATFORMS:
        raise HTTPException(404, "Nepoznata platforma.")
    return {
        "platform": platform,
        "sudo_commands": privileges.sudo_commands(platform),
        "sudoers": privileges.sudoers_file(platform),
        "unprivileged": privileges.UNPRIVILEGED.get(platform, []),
        "notes": privileges.NOTES.get(platform, []),
    }


def pool_dict(pool: StoragePool, device: Device) -> dict[str, Any]:
    return {
        "id": pool.id,
        "device_id": pool.device_id,
        "device_name": device.name,
        "name": pool.name,
        "technology": pool.technology,
        "status": pool.status,
        "healthy": pool.healthy,
        "redundancy": pool.redundancy,
        "capacity_bytes": pool.capacity_bytes,
        "used_bytes": pool.used_bytes,
        "free_bytes": pool.free_bytes,
        "read_errors": pool.read_errors,
        "write_errors": pool.write_errors,
        "checksum_errors": pool.checksum_errors,
        "message": pool.message,
        "data_errors": pool.data_errors,
        "scan_type": pool.scan_type,
        "scan_state": pool.scan_state,
        "scan_progress": pool.scan_progress,
        "scan_errors": pool.scan_errors,
        "scan_finished_at": pool.scan_finished_at,
        "scan_text": pool.scan_text,
        "members": pool.members or [],
        "details": pool.details or {},
        "first_seen_at": pool.first_seen_at,
        "last_seen_at": pool.last_seen_at,
        "is_present": pool.is_present,
    }


@router.get("/pools")
async def list_pools(
    device_id: int | None = None,
    _: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    query = (
        select(StoragePool, Device).join(Device, Device.id == StoragePool.device_id)
        .where(Device.deleted_at.is_(None))
        .order_by(Device.name, StoragePool.technology, StoragePool.name)
    )
    if device_id is not None:
        query = query.where(StoragePool.device_id == device_id)
    return [pool_dict(pool, device) for pool, device in (await db.execute(query)).all()]


@router.get("/pools/{pool_id}")
async def get_pool(pool_id: int, _: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = (await db.execute(
        select(StoragePool, Device).join(Device, Device.id == StoragePool.device_id)
        .where(StoragePool.id == pool_id, Device.deleted_at.is_(None))
    )).first()
    if row is None:
        raise HTTPException(404, "Pool nije pronađen.")
    pool, device = row
    data = pool_dict(pool, device)
    samples = await db.scalars(
        select(PoolSample).where(PoolSample.pool_id == pool_id).order_by(PoolSample.collected_at.desc()).limit(200)
    )
    data["samples"] = [
        {c.name: getattr(s, c.name) for c in PoolSample.__table__.columns if c.name != "pool_id"} for s in samples
    ]
    return data
