"""Čuvanje rezultata ciklusa: inventar diskova, SMART očitavanja, self-testovi i stanje skladišta."""

from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .adapters.model import CollectResult, DiskReading
from .adapters.storage import disk_key
from .models import Disk, DiskSample, PoolSample, SmartTest, StoragePool

_DISK_FIELDS = ("device_path", "smart_type", "model", "vendor", "serial_number", "wwn", "firmware", "disk_type",
                "interface_type", "capacity_bytes", "rotation_rate", "form_factor")
_SAMPLE_FIELDS = (
    "smart_available", "smart_health", "smart_message", "temperature_c", "power_on_hours", "power_cycles",
    "reallocated_sectors", "pending_sectors", "uncorrectable_sectors", "crc_errors", "reported_uncorrect",
    "load_cycles", "start_stop_count", "ssd_life_left", "total_lbas_written", "percentage_used", "available_spare",
    "available_spare_threshold", "media_errors", "critical_warning", "unsafe_shutdowns", "data_units_read",
    "data_units_written", "host_read_commands", "host_write_commands", "controller_busy_time", "error_log_entries",
    "warning_temp_time", "critical_temp_time", "error_log_count", "self_test_running", "self_test_status",
)
_POOL_FIELDS = ("status", "healthy", "redundancy", "capacity_bytes", "used_bytes", "free_bytes", "read_errors",
                "write_errors", "checksum_errors", "message", "data_errors", "scan_type", "scan_state",
                "scan_progress", "scan_errors", "scan_finished_at", "scan_text")
_POOL_SAMPLE_FIELDS = ("status", "healthy", "read_errors", "write_errors", "checksum_errors", "capacity_bytes",
                       "used_bytes", "free_bytes", "scan_type", "scan_state", "scan_progress", "scan_errors")

# Postgres BIGINT; neki brojači (npr. spakovani raw) mogu biti veći – tada se ne čuvaju.
_MAX_BIGINT = 2**63 - 1
_MAX_INT = 2**31 - 1


def _clip(value: Any, limit: int) -> Any:
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > limit:
        return None
    return value


def _identifier(reading: DiskReading) -> str:
    return (reading.stable_identifier or f"path-{reading.device_path}")[:255]


def _trim(value: Any, length: int) -> Any:
    return value[:length] if isinstance(value, str) else value


async def save_disks(db: AsyncSession, device_id: int, run_id: int, result: CollectResult, now: datetime) -> dict[str, int]:
    """Vraća mapu ime diska (sda, ada0, nvme0) → disk_id, za povezivanje sa članovima pool-ova."""
    disks = list(await db.scalars(select(Disk).where(Disk.device_id == device_id).order_by(Disk.last_seen_at)))
    existing = {d.stable_identifier: d for d in disks}
    # Disk u standby-ju (ili bez SMART-a) ne vraća WWN ni serijski broj. Tada je to poznati disk na istoj putanji,
    # a ne nov disk – inače bi se pravi disk pogrešno označio kao nestao.
    by_path = {d.device_path: d for d in disks if not d.stable_identifier.startswith("path-")}
    by_key: dict[str, int] = {}
    seen: set[str] = set()
    int_columns = {c.name for c in DiskSample.__table__.columns if type(c.type).__name__ in ("Integer", "BigInteger")}
    small_int = {c.name for c in DiskSample.__table__.columns if type(c.type).__name__ == "Integer"}

    for reading in result.disks:
        ident = _identifier(reading)
        if reading.stable_identifier is None and reading.device_path in by_path:
            ident = by_path[reading.device_path].stable_identifier
        if ident in seen:  # isti disk vidljiv kroz dve putanje (npr. multipath) – čuva se jednom
            continue
        seen.add(ident)
        disk = existing.get(ident)
        if disk is None:
            disk = Disk(device_id=device_id, stable_identifier=ident, first_seen_at=now, last_seen_at=now)
            db.add(disk)
        for name in _DISK_FIELDS:
            value = getattr(reading, name)
            # „unknown” tip (npr. disk u standby-ju) ne briše tip koji je ranije pouzdano utvrđen.
            if name == "disk_type" and value == "unknown" and disk.disk_type not in (None, "unknown"):
                continue
            if value is not None or name == "device_path":
                setattr(disk, name, _trim(value, 255))
        disk.last_seen_at = now
        disk.is_present = True
        if reading.raw is not None:
            disk.last_raw = reading.raw
        await db.flush()

        sample = DiskSample(disk_id=disk.id, run_id=run_id, collected_at=now, device_path=reading.device_path)
        for name in _SAMPLE_FIELDS:
            value = getattr(reading, name)
            if name in int_columns:
                value = _clip(value, _MAX_INT if name in small_int else _MAX_BIGINT)
            setattr(sample, name, _trim(value, 255) if name == "self_test_status" else value)
        sample.attributes = reading.attributes or None
        db.add(sample)
        await db.flush()
        disk.latest_sample_id = sample.id

        for test in reading.self_tests:
            await db.execute(
                insert(SmartTest)
                .values(disk_id=disk.id, test_type=test.test_type[:64], status=test.status[:128], passed=test.passed,
                        lifetime_hours=test.lifetime_hours if test.lifetime_hours is not None else -1,
                        remaining_percent=test.remaining_percent, first_seen_at=now)
                .on_conflict_do_nothing()
            )
        key = disk_key(reading.device_path)
        if key:
            by_key[key] = disk.id

    if result.disks_complete:
        for ident, disk in existing.items():
            if ident not in seen and disk.is_present:
                disk.is_present = False
    return by_key


async def save_pools(db: AsyncSession, device_id: int, result: CollectResult, disk_ids: dict[str, int],
                     now: datetime) -> None:
    existing = {(p.technology, p.name): p for p in
                await db.scalars(select(StoragePool).where(StoragePool.device_id == device_id))}
    seen: set[tuple[str, str]] = set()
    for reading in result.pools:
        key = (reading.technology, reading.name[:255])
        if key in seen:
            continue
        seen.add(key)
        pool = existing.get(key)
        if pool is None:
            pool = StoragePool(device_id=device_id, technology=key[0], name=key[1], first_seen_at=now, last_seen_at=now)
            db.add(pool)
        for name in _POOL_FIELDS:
            setattr(pool, name, _clip(getattr(reading, name), _MAX_BIGINT))
        pool.status = (reading.status or "?")[:64]
        pool.members = [
            {**asdict(m), "disk_id": disk_ids.get(m.disk_path or "")} for m in reading.members
        ] or None
        pool.details = reading.details or None
        pool.last_seen_at = now
        pool.is_present = True
        await db.flush()
        sample = PoolSample(pool_id=pool.id, collected_at=now)
        for name in _POOL_SAMPLE_FIELDS:
            setattr(sample, name, _clip(getattr(pool, name), _MAX_BIGINT))
        db.add(sample)

    for key, pool in existing.items():
        if key not in seen and key[0] in result.pool_sources and pool.is_present:
            pool.is_present = False
