"""Grafikoni, statistika, izveštaji i izvoz (Faza 3)."""

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import analytics, export, reports, settings_store
from ..db import get_db
from ..deps import current_user
from ..models import Device, Disk, DiskSample, StoragePool, User
from ..routers.storage import disk_findings, last_smart_samples, standby_ids

router = APIRouter(prefix="/api", tags=["analytics"])

MAX_SERIES = 8  # više linija na jednom grafikonu postaje nečitljivo (spec. §10.5 „poređenje više diskova”)


async def _period(db: AsyncSession, date_from: datetime | None, date_to: datetime | None,
                  default_days: int = 7) -> tuple[datetime, datetime, ZoneInfo]:
    tz = ZoneInfo(await settings_store.get_setting(db, settings_store.TIMEZONE))
    end = date_to or datetime.now(tz)
    start = date_from or end - timedelta(days=default_days)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if start >= end:
        raise HTTPException(422, "Početak perioda mora biti pre kraja.")
    if end - start > timedelta(days=3660):
        raise HTTPException(422, "Period može biti najviše 10 godina.")
    return start.astimezone(tz), end.astimezone(tz), tz


def _ids(raw: str) -> list[int]:
    try:
        ids = sorted({int(x) for x in raw.split(",") if x.strip()})
    except ValueError as exc:
        raise HTTPException(422, "Neispravan spisak identifikatora.") from exc
    if not ids:
        raise HTTPException(422, "Izaberite bar jedan disk ili pool.")
    if len(ids) > MAX_SERIES:
        raise HTTPException(422, f"Na jednom grafikonu može biti najviše {MAX_SERIES} serija.")
    return ids


def _bucket(bucket: str, start: datetime, end: datetime) -> str:
    if bucket == "auto":
        return analytics.auto_bucket(start, end)
    if bucket not in analytics.BUCKETS:
        raise HTTPException(422, "Nepoznat interval agregacije.")
    if bucket == "raw" and end - start > timedelta(days=93):
        raise HTTPException(422, "Sirova merenja se prikazuju za period do 3 meseca. Izaberite satni ili dnevni prikaz.")
    return bucket


def _download(data: bytes, fmt: str, name: str) -> Response:
    filename = f"{name}.{fmt}"
    return Response(
        data,
        media_type=export.FORMATS[fmt],
        headers={"Content-Disposition": f"attachment; filename=\"{filename.encode('ascii', 'ignore').decode()}\"; "
                                        f"filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/metrics/catalog")
async def metrics_catalog(_: User = Depends(current_user)) -> dict[str, Any]:
    return {
        "disk": {k: {"label": m.label, "unit": m.unit, "kind": m.kind} for k, m in analytics.DISK_METRICS.items()},
        "pool": {k: {"label": m.label, "unit": m.unit, "kind": m.kind} for k, m in analytics.POOL_METRICS.items()},
        "max_series": MAX_SERIES,
    }


async def _disk_labels(db: AsyncSession, ids: list[int]) -> dict[int, str]:
    rows = (await db.execute(
        select(Disk, Device).join(Device, Device.id == Disk.device_id).where(Disk.id.in_(ids), Device.deleted_at.is_(None))
    )).all()
    return {d.id: f"{dev.name} · {d.device_path} · {d.model or '?'}" for d, dev in rows}


async def _pool_labels(db: AsyncSession, ids: list[int]) -> dict[int, str]:
    rows = (await db.execute(
        select(StoragePool, Device).join(Device, Device.id == StoragePool.device_id)
        .where(StoragePool.id.in_(ids), Device.deleted_at.is_(None))
    )).all()
    return {p.id: f"{dev.name} · {p.name}" for p, dev in rows}


async def _series_response(db: AsyncSession, kind: str, ids_raw: str, metric_name: str, date_from: datetime | None,
                           date_to: datetime | None, bucket: str, fmt: str, user: User) -> Any:
    catalog = analytics.DISK_METRICS if kind == "disk" else analytics.POOL_METRICS
    metric = catalog.get(metric_name)
    if metric is None:
        raise HTTPException(422, "Nepoznata metrika.")
    ids = _ids(ids_raw)
    start, end, tz = await _period(db, date_from, date_to)
    b = _bucket(bucket, start, end)
    labels = await (_disk_labels(db, ids) if kind == "disk" else _pool_labels(db, ids))
    ids = [i for i in ids if i in labels]
    if not ids:
        raise HTTPException(404, "Izabrani diskovi ili pool-ovi nisu pronađeni.")
    table, column = ("disk_samples", "disk_id") if kind == "disk" else ("pool_samples", "pool_id")
    data = await analytics.series(db, table, column, ids, metric, start, end, b)
    stats = {i: await analytics.metric_stats(db, table, column, i, metric, start, end) for i in ids}

    if fmt != "json":
        if fmt not in export.FORMATS:
            raise HTTPException(422, "Nepoznat format izvoza.")
        rows = [{"entity": labels[i], "t": p["t"], "value": p["value"], "min": p["min"], "max": p["max"], "n": p["n"]}
                for i in ids for p in data[i]]
        bucket_label = {"raw": "sirovo", "hour": "satno", "day": "dnevno", "week": "nedeljno"}[b]
        report = export.Report(
            f"{metric.label}" + (f" ({metric.unit})" if metric.unit else ""),
            [export.Column("entity", "Disk / pool"), export.Column("t", "Vreme", "datetime"),
             export.Column("value", "Vrednost", "float"), export.Column("min", "Min", "float"),
             export.Column("max", "Maks", "float"), export.Column("n", "Očitavanja", "int")],
            rows,
            f"Period: {start.strftime('%d.%m.%Y. %H:%M')} – {end.strftime('%d.%m.%Y. %H:%M')} · interval: {bucket_label}",
        )
        return _download(export.render(report, fmt, tz, user.username), fmt, f"smartdisk-{metric_name}-{start:%Y%m%d}-{end:%Y%m%d}")

    return {
        "metric": metric_name, "label": metric.label, "unit": metric.unit, "kind": metric.kind,
        "bucket": b, "from": start, "to": end,
        "series": [{"id": i, "label": labels[i], "points": data[i], "stats": stats[i]} for i in ids],
    }


@router.get("/metrics/disks")
async def disk_series(
    ids: str,
    metric: str,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    bucket: str = "auto",
    format: str = "json",
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return await _series_response(db, "disk", ids, metric, date_from, date_to, bucket, format, user)


@router.get("/metrics/pools")
async def pool_series(
    ids: str,
    metric: str,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    bucket: str = "auto",
    format: str = "json",
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return await _series_response(db, "pool", ids, metric, date_from, date_to, bucket, format, user)


@router.get("/metrics/availability")
async def device_availability(
    device_ids: str | None = None,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    bucket: str = "auto",
    _: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    devices = list(await db.scalars(select(Device).where(Device.deleted_at.is_(None))))
    names = {d.id: d.name for d in devices}
    ids = [i for i in (_ids(device_ids) if device_ids else list(names)) if i in names]
    start, end, _tz = await _period(db, date_from, date_to)
    b = _bucket(bucket, start, end)
    if b == "raw":
        b = "hour"
    data = await analytics.availability(db, ids, start, end, b) if ids else {"buckets": {}, "outages": {}, "totals": {}}
    return {
        "bucket": b, "from": start, "to": end,
        "devices": [{"id": i, "name": names[i], "buckets": data["buckets"][i], "outages": data["outages"][i],
                     "totals": data["totals"][i]} for i in ids],
    }


TREND_METRICS = ["temperature_c", "power_on_hours", "reallocated_sectors", "pending_sectors", "uncorrectable_sectors",
                 "crc_errors", "media_errors", "percentage_used", "available_spare", "data_units_written"]


@router.get("/disks/{disk_id}/trends")
async def disk_trends(disk_id: int, _: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Promene za 24 h, 7 dana i 30 dana; metrike koje disk ne prijavljuje se izostavljaju."""
    disk = await db.get(Disk, disk_id)
    if disk is None:
        raise HTTPException(404, "Disk nije pronađen.")
    trends = await analytics.disk_trends(db, disk_id, TREND_METRICS)
    return {k: v for k, v in trends.items() if v["30d"]["last"] is not None}


@router.get("/stats/overview")
async def stats_overview(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    _: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Statistika celog sistema za period (spec. §10.5): temperature, radni sati, istrošenost, pool-ovi, dostupnost."""
    start, end, _tz = await _period(db, date_from, date_to)
    rows = (await db.execute(
        select(Disk, Device, DiskSample).join(Device, Device.id == Disk.device_id)
        .outerjoin(DiskSample, DiskSample.id == Disk.latest_sample_id)
        .where(Device.deleted_at.is_(None), Disk.is_present.is_(True))
    )).all()
    last = await last_smart_samples(db, standby_ids([(d, s) for d, _, s in rows]))
    disk_info = {d.id: {"id": d.id, "label": f"{dev.name} · {d.device_path} · {d.model or '?'}",
                        "disk_type": d.disk_type, "sample": last.get(d.id) or s} for d, dev, s in rows}
    temps = {r["disk_id"]: r for r in (await db.execute(text("""
        SELECT disk_id, min(temperature_c) AS min, max(temperature_c) AS max, avg(temperature_c)::float AS avg,
               count(*) FILTER (WHERE smart_health = 'failed') AS failed_samples, count(*) AS n
        FROM disk_samples WHERE collected_at BETWEEN :start AND :end GROUP BY disk_id
    """), {"start": start, "end": end})).mappings()}
    temperature = sorted(
        [{"id": i, "label": info["label"], "min": temps[i]["min"], "max": temps[i]["max"], "avg": temps[i]["avg"]}
         for i, info in disk_info.items() if i in temps and temps[i]["max"] is not None],
        key=lambda r: -(r["max"] or 0),
    )
    poh = sorted([{"id": i, "label": info["label"], "value": info["sample"].power_on_hours}
                  for i, info in disk_info.items() if info["sample"] and info["sample"].power_on_hours is not None],
                 key=lambda r: -r["value"])[:10]
    wear = []
    for i, info in disk_info.items():
        s = info["sample"]
        if not s:
            continue
        if s.percentage_used is not None:
            wear.append({"id": i, "label": info["label"], "value": s.percentage_used, "source": "NVMe percentage used"})
        elif s.ssd_life_left is not None:
            wear.append({"id": i, "label": info["label"], "value": 100 - s.ssd_life_left, "source": "100 − SSD life left"})
    wear.sort(key=lambda r: -r["value"])
    states = {"ok": 0, "warning": 0, "critical": 0, "unknown": 0}
    for d, _dev, s in rows:
        states[disk_findings(s, d.is_present, last.get(d.id))[0]] += 1
    smart_failed = sum(1 for i in temps if temps[i]["failed_samples"])

    pools = (await db.execute(
        select(StoragePool, Device).join(Device, Device.id == StoragePool.device_id)
        .where(Device.deleted_at.is_(None), StoragePool.is_present.is_(True),
               StoragePool.technology.in_(("zfs", "lvm_thin", "pve_storage", "synology_volume", "mdadm")))
    )).all()
    pool_trend = []
    for pool, device in pools:
        st = await analytics.metric_stats(db, "pool_samples", "pool_id", pool.id, analytics.POOL_METRICS["used_bytes"], start, end)
        pool_trend.append({
            "id": pool.id, "label": f"{device.name} · {pool.name}", "technology": pool.technology,
            "capacity_bytes": pool.capacity_bytes, "used_bytes": pool.used_bytes, "delta_bytes": st["delta"],
            "rate_bytes_per_day": st["rate_per_day"],
            "days_to_full": (pool.free_bytes / st["rate_per_day"])
            if st["rate_per_day"] and st["rate_per_day"] > 0 and pool.free_bytes else None,
        })
    pool_trend.sort(key=lambda r: -((r["used_bytes"] or 0) / (r["capacity_bytes"] or 1)))

    devices = list(await db.scalars(select(Device).where(Device.deleted_at.is_(None)).order_by(Device.name)))
    avail = await analytics.availability(db, [d.id for d in devices], start, end, "day") if devices else {"totals": {}}
    return {
        "from": start, "to": end,
        "disk_states": states, "smart_failed_disks": smart_failed,
        "temperature": temperature, "power_on_hours": poh, "wear": wear[:10], "pools": pool_trend,
        "availability": [{"id": d.id, "name": d.name, **avail["totals"][d.id]} for d in devices],
    }


@router.get("/reports")
async def report_kinds(_: User = Depends(current_user)) -> dict[str, str]:
    return reports.REPORT_KINDS


@router.get("/reports/{kind}")
async def get_report(
    kind: str,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    device_id: int | None = None,
    format: str = "json",
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if kind not in reports.REPORT_KINDS:
        raise HTTPException(404, "Nepoznat izveštaj.")
    start, end, tz = await _period(db, date_from, date_to)
    report = await reports.build(db, kind, start, end, device_id)
    if format == "json":
        return {
            "title": report.title, "subtitle": report.subtitle, "notes": report.notes,
            "columns": [{"key": c.key, "label": c.label, "kind": c.kind} for c in report.columns],
            "rows": report.rows,
        }
    if format not in export.FORMATS:
        raise HTTPException(422, "Nepoznat format izvoza.")
    return _download(export.render(report, format, tz, user.username), format,
                     f"smartdisk-{kind}-{start:%Y%m%d}-{end:%Y%m%d}")
