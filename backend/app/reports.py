"""Izveštaji (spec. §10.7): isti podaci za prikaz u UI-ju (JSON) i za izvoz (CSV, XLSX, PDF)."""

from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from . import analytics
from .constants import PLATFORMS
from .export import Column, Report
from .models import Device, Disk, DiskSample, StoragePool
from .routers.devices import device_status
from .routers.storage import disk_findings, last_smart_samples, standby_ids

REPORT_KINDS: dict[str, str] = {
    "devices": "Stanje uređaja",
    "disks": "Inventar diskova",
    "disk_warnings": "Diskovi sa upozorenjima",
    "smart_changes": "SMART promene u periodu",
    "pool_errors": "Stanje skladišta (ZFS/RAID) i greške",
    "availability": "Nedostupnost uređaja",
}

DEVICE_STATUS_LABEL = {"ok": "Dostupan", "error": "Greška", "waiting": "Čeka prvo prikupljanje",
                       "disabled": "Nadzor isključen", "not_configured": "Nije podešen"}
STATE_LABEL = {"ok": "Bez upozorenja", "warning": "Upozorenje", "critical": "Kritično", "unknown": "Nema podataka"}
SMART_LABEL = {"passed": "PASSED", "failed": "FAILED", "unknown": "nepoznato", "unavailable": "nedostupan",
               "standby": "standby"}
TYPE_LABEL = {"hdd": "HDD", "ssd": "SSD", "nvme": "NVMe", "sas": "SAS", "usb": "USB", "unknown": "nepoznat"}

# Brojači koji kod ispravnog diska ne rastu; svaki rast u periodu ulazi u izveštaj o SMART promenama.
CHANGE_COUNTERS = ["reallocated_sectors", "pending_sectors", "uncorrectable_sectors", "reported_uncorrect",
                   "crc_errors", "media_errors", "error_log_entries", "error_log_count", "percentage_used"]
CHANGE_LABELS = {
    "reallocated_sectors": "Realocirani sektori",
    "pending_sectors": "Pending sektori",
    "uncorrectable_sectors": "Neispravljivi sektori",
    "reported_uncorrect": "Prijavljene neispravljive greške",
    "crc_errors": "UDMA CRC greške",
    "media_errors": "NVMe media greške",
    "error_log_entries": "NVMe log grešaka",
    "error_log_count": "SMART log grešaka",
    "percentage_used": "NVMe istrošenost (%)",
}


def _hours(seconds: float | None) -> float | None:
    return round(seconds / 3600, 2) if seconds is not None else None


async def _devices(db: AsyncSession) -> list[Device]:
    return list(await db.scalars(select(Device).where(Device.deleted_at.is_(None)).order_by(Device.name)))


async def _disk_rows(db: AsyncSession, device_id: int | None = None) -> list[tuple[Disk, Device, DiskSample | None]]:
    query = (
        select(Disk, Device, DiskSample).join(Device, Device.id == Disk.device_id)
        .outerjoin(DiskSample, DiskSample.id == Disk.latest_sample_id)
        .where(Device.deleted_at.is_(None)).order_by(Device.name, Disk.device_path)
    )
    if device_id is not None:
        query = query.where(Disk.device_id == device_id)
    return list((await db.execute(query)).all())


async def build(db: AsyncSession, kind: str, start: datetime, end: datetime, device_id: int | None = None) -> Report:
    period = f"Period: {start.strftime('%d.%m.%Y. %H:%M')} – {end.strftime('%d.%m.%Y. %H:%M')}"
    if kind == "devices":
        return await _report_devices(db, start, end, period)
    if kind == "disks":
        return await _report_disks(db, device_id, only_warnings=False)
    if kind == "disk_warnings":
        return await _report_disks(db, device_id, only_warnings=True)
    if kind == "smart_changes":
        return await _report_smart_changes(db, start, end, period, device_id)
    if kind == "pool_errors":
        return await _report_pools(db, start, end, period, device_id)
    if kind == "availability":
        return await _report_availability(db, start, end, period)
    raise ValueError(kind)


async def _report_devices(db: AsyncSession, start: datetime, end: datetime, period: str) -> Report:
    devices = await _devices(db)
    ids = [d.id for d in devices]
    avail = await analytics.availability(db, ids, start, end, "day") if ids else {"totals": {}}
    disks = await _disk_rows(db)
    last = await last_smart_samples(db, standby_ids([(d, s) for d, _, s in disks]))
    rows = []
    for device in devices:
        own = [(d, s) for d, dev, s in disks if dev.id == device.id]
        states = [disk_findings(s, d.is_present, last.get(d.id))[0] for d, s in own]
        t = avail["totals"].get(device.id, {})
        rows.append({
            "name": device.name, "platform": PLATFORMS.get(device.platform, device.platform), "host": device.host,
            "status": DEVICE_STATUS_LABEL[device_status(device)], "os": device.os_info,
            "disks": sum(1 for d, _ in own if d.is_present),
            "warnings": sum(1 for s in states if s in ("warning", "critical")),
            "last_success": device.last_success_at, "last_error": device.last_error,
            "availability": t.get("availability_percent"), "outages": t.get("outages"),
            "outage_hours": _hours(t.get("outage_seconds")),
        })
    return Report(REPORT_KINDS["devices"], [
        Column("name", "Uređaj"), Column("platform", "Platforma"), Column("host", "Adresa"),
        Column("status", "Stanje"), Column("os", "Sistem"), Column("disks", "Diskova", "int"),
        Column("warnings", "Diskova sa upozorenjem", "int"), Column("last_success", "Poslednje uspešno", "datetime"),
        Column("availability", "Dostupnost u periodu (%)", "float"), Column("outages", "Nedostupnosti", "int"),
        Column("outage_hours", "Nedostupno (h)", "float"), Column("last_error", "Poslednja greška"),
    ], rows, period, ["Dostupnost se računa iz planiranih i ručnih ciklusa prikupljanja (testovi konekcije se ne računaju)."])


async def _report_disks(db: AsyncSession, device_id: int | None, only_warnings: bool) -> Report:
    rows = []
    disk_rows = await _disk_rows(db, device_id)
    last = await last_smart_samples(db, standby_ids([(d, s) for d, _, s in disk_rows]))
    for disk, device, sample in disk_rows:
        state, reasons = disk_findings(sample, disk.is_present, last.get(disk.id))
        if only_warnings and state == "ok":
            continue
        s = last.get(disk.id) or sample
        rows.append({
            "device": device.name, "path": disk.device_path, "model": disk.model, "serial": disk.serial_number,
            "type": TYPE_LABEL.get(disk.disk_type, disk.disk_type), "capacity_gb": round(disk.capacity_bytes / 1e9, 1) if disk.capacity_bytes else None,
            "present": disk.is_present, "state": STATE_LABEL[state], "reasons": " ".join(reasons),
            "smart": SMART_LABEL.get(s.smart_health) if s else None, "temp": s.temperature_c if s else None,
            "poh": s.power_on_hours if s else None, "realloc": s.reallocated_sectors if s else None,
            "pending": s.pending_sectors if s else None, "uncorr": s.uncorrectable_sectors if s else None,
            "crc": s.crc_errors if s else None, "media": s.media_errors if s else None,
            "wear": s.percentage_used if s else None, "read_at": s.collected_at if s else None,
        })
    title = REPORT_KINDS["disk_warnings" if only_warnings else "disks"]
    notes = ["Prazno polje znači da vrednost nije dostupna (nije 0)."]
    if only_warnings:
        notes.insert(0, "Obuhvata diskove sa upozorenjem, kritičnim stanjem ili bez podataka (nedostupan SMART, standby, nestao disk).")
    return Report(title, [
        Column("device", "Uređaj"), Column("path", "Putanja"), Column("model", "Model"), Column("serial", "Serijski broj"),
        Column("type", "Tip"), Column("capacity_gb", "Kapacitet (GB)", "float"), Column("present", "Prisutan"),
        Column("state", "Stanje"), Column("smart", "SMART"), Column("temp", "Temp. (°C)", "int"),
        Column("poh", "Sati rada", "int"), Column("realloc", "Realoc.", "int"), Column("pending", "Pending", "int"),
        Column("uncorr", "Uncorr.", "int"), Column("crc", "CRC", "int"), Column("media", "NVMe media", "int"),
        Column("wear", "NVMe istroš. (%)", "int"), Column("read_at", "Očitano", "datetime"), Column("reasons", "Razlozi"),
    ], rows, None, notes)


async def _report_smart_changes(db: AsyncSession, start: datetime, end: datetime, period: str,
                                device_id: int | None) -> Report:
    cols = ", ".join(CHANGE_COUNTERS)
    first_last = (await db.execute(text(f"""
        WITH ranked AS (
            SELECT disk_id, collected_at, {cols},
                   row_number() OVER (PARTITION BY disk_id ORDER BY collected_at) AS a,
                   row_number() OVER (PARTITION BY disk_id ORDER BY collected_at DESC) AS d
            FROM disk_samples WHERE collected_at BETWEEN :start AND :end
        ) SELECT * FROM ranked WHERE a = 1 OR d = 1
    """), {"start": start, "end": end})).mappings().all()
    by_disk: dict[int, dict[str, Any]] = {}
    for r in first_last:
        entry = by_disk.setdefault(r["disk_id"], {})
        if r["a"] == 1:
            entry["first"] = r
        if r["d"] == 1:
            entry["last"] = r
    disks = {d.id: (d, dev) for d, dev, _ in await _disk_rows(db, device_id)}
    rows = []
    for disk_id, entry in by_disk.items():
        if disk_id not in disks or "first" not in entry or "last" not in entry:
            continue
        disk, device = disks[disk_id]
        for counter in CHANGE_COUNTERS:
            before, after = entry["first"][counter], entry["last"][counter]
            if before is None or after is None or after == before:
                continue
            rows.append({
                "device": device.name, "disk": f"{disk.device_path} · {disk.model or '?'}", "serial": disk.serial_number,
                "attribute": CHANGE_LABELS[counter], "before": before, "after": after, "delta": after - before,
                "from": entry["first"]["collected_at"], "to": entry["last"]["collected_at"],
            })
    rows.sort(key=lambda r: (r["device"], r["disk"], r["attribute"]))
    return Report(REPORT_KINDS["smart_changes"], [
        Column("device", "Uređaj"), Column("disk", "Disk"), Column("serial", "Serijski broj"),
        Column("attribute", "Vrednost"), Column("before", "Na početku", "int"), Column("after", "Na kraju", "int"),
        Column("delta", "Promena", "int"), Column("from", "Prvo očitavanje", "datetime"),
        Column("to", "Poslednje očitavanje", "datetime"),
    ], rows, period, ["Prikazani su samo brojači čija se vrednost u periodu promenila. Rast realociranih, pending i "
                      "neispravljivih sektora ili NVMe media grešaka znači da disk treba pratiti."])


async def _report_pools(db: AsyncSession, start: datetime, end: datetime, period: str, device_id: int | None) -> Report:
    query = (select(StoragePool, Device).join(Device, Device.id == StoragePool.device_id)
             .where(Device.deleted_at.is_(None), StoragePool.technology.in_(("zfs", "mdadm", "lvm_thin", "lvm_vg")))
             .order_by(Device.name, StoragePool.name))
    if device_id is not None:
        query = query.where(StoragePool.device_id == device_id)
    pools = list((await db.execute(query)).all())
    stats = {}
    if pools:
        for r in (await db.execute(text("""
            SELECT pool_id, count(*) AS n, count(*) FILTER (WHERE healthy IS FALSE) AS unhealthy,
                   max(read_errors) AS r, max(write_errors) AS w, max(checksum_errors) AS c,
                   max(scan_errors) AS scan_errors
            FROM pool_samples WHERE pool_id = ANY(:ids) AND collected_at BETWEEN :start AND :end GROUP BY pool_id
        """), {"ids": [p.id for p, _ in pools], "start": start, "end": end})).mappings():
            stats[r["pool_id"]] = r
    rows = []
    for pool, device in pools:
        s = stats.get(pool.id, {})
        rows.append({
            "device": device.name, "pool": pool.name, "tech": pool.technology, "redundancy": pool.redundancy,
            "status": pool.status, "healthy": {True: "da", False: "NE", None: "nepoznato"}[pool.healthy],
            "present": pool.is_present, "unhealthy": s.get("unhealthy"), "samples": s.get("n"),
            "r": s.get("r"), "w": s.get("w"), "c": s.get("c"),
            "scan": f"{pool.scan_type or ''} {pool.scan_state or ''}".strip() or None,
            "scan_finished": pool.scan_finished_at, "scan_errors": pool.scan_errors,
            "used_pct": round(100 * pool.used_bytes / pool.capacity_bytes, 1)
            if pool.used_bytes is not None and pool.capacity_bytes else None,
            "message": pool.message,
        })
    return Report(REPORT_KINDS["pool_errors"], [
        Column("device", "Uređaj"), Column("pool", "Pool / niz"), Column("tech", "Tehnologija"),
        Column("redundancy", "Redundansa"), Column("status", "Stanje"), Column("healthy", "Ispravan"),
        Column("unhealthy", "Neispravnih očitavanja", "int"), Column("samples", "Očitavanja", "int"),
        Column("r", "Maks. READ", "int"), Column("w", "Maks. WRITE", "int"), Column("c", "Maks. CKSUM", "int"),
        Column("scan", "Scrub/resilver"), Column("scan_finished", "Završen"), Column("scan_errors", "Grešaka u scrub-u", "int"),
        Column("used_pct", "Zauzeto (%)", "float"), Column("message", "Poruka sistema"),
    ], rows, period, ["Greške i broj neispravnih očitavanja odnose se na izabrani period; stanje i scrub su poslednje očitano stanje."])


async def _report_availability(db: AsyncSession, start: datetime, end: datetime, period: str) -> Report:
    devices = await _devices(db)
    if not devices:
        return Report(REPORT_KINDS["availability"], [], [], period)
    avail = await analytics.availability(db, [d.id for d in devices], start, end, "day")
    rows = []
    for device in devices:
        for outage in avail["outages"][device.id]:
            rows.append({
                "device": device.name, "start": outage["start"], "end": outage["end"],
                "hours": _hours(outage["duration_seconds"]), "failed_runs": outage["failed_runs"],
                "ongoing": outage["end"] is None, "reason": outage["reason"],
            })
    totals = "; ".join(
        f"{d.name}: dostupnost {avail['totals'][d.id]['availability_percent'] if avail['totals'][d.id]['availability_percent'] is not None else '—'}%"
        f", {avail['totals'][d.id]['outages']} nedostupnosti" for d in devices
    )
    return Report(REPORT_KINDS["availability"], [
        Column("device", "Uređaj"), Column("start", "Početak", "datetime"), Column("end", "Kraj", "datetime"),
        Column("hours", "Trajanje (h)", "float"), Column("failed_runs", "Neuspelih ciklusa", "int"),
        Column("ongoing", "I dalje traje"), Column("reason", "Razlog"),
    ], rows, period, [f"Ukupno – {totals}.", "Nedostupnost traje od prvog neuspelog do prvog sledećeg uspešnog ciklusa."])
