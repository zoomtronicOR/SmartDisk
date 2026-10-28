"""Vremenske serije, statistika, dostupnost i dnevni agregati (Faza 3).

Sve agregacije rade u bazi (date_trunc po vremenskoj zoni prikaza), tako da odgovor ostaje mali
i kada je u bazi godina merenja. Imena metrika i agregacija dolaze isključivo iz rečnika ispod,
nikad iz zahteva, pa se SQL ne sastavlja od korisničkog unosa.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import settings_store


@dataclass(frozen=True)
class Metric:
    column: str
    label: str
    unit: str
    agg: str  # avg / max / min – kako se vrednost svodi na interval
    daily: str | None  # kolona u disk_daily/pool_daily (None = nema u agregatu)
    kind: str = "gauge"  # gauge / counter (brojač koji ne bi smeo da raste)


DISK_METRICS: dict[str, Metric] = {
    "temperature_c": Metric("temperature_c", "Temperatura", "°C", "avg", "temperature_avg"),
    "power_on_hours": Metric("power_on_hours", "Sati rada", "h", "max", "power_on_hours"),
    "power_cycles": Metric("power_cycles", "Broj uključivanja", "", "max", "power_cycles"),
    "reallocated_sectors": Metric("reallocated_sectors", "Realocirani sektori", "", "max", "reallocated_sectors", "counter"),
    "pending_sectors": Metric("pending_sectors", "Sektori na čekanju (pending)", "", "max", "pending_sectors", "counter"),
    "uncorrectable_sectors": Metric("uncorrectable_sectors", "Neispravljivi sektori", "", "max", "uncorrectable_sectors", "counter"),
    "reported_uncorrect": Metric("reported_uncorrect", "Prijavljene neispravljive greške", "", "max", "reported_uncorrect", "counter"),
    "crc_errors": Metric("crc_errors", "UDMA CRC greške", "", "max", "crc_errors", "counter"),
    "media_errors": Metric("media_errors", "NVMe media greške", "", "max", "media_errors", "counter"),
    "error_log_entries": Metric("error_log_entries", "NVMe unosi u logu grešaka", "", "max", "error_log_entries", "counter"),
    "unsafe_shutdowns": Metric("unsafe_shutdowns", "Nebezbedna gašenja", "", "max", "unsafe_shutdowns"),
    "percentage_used": Metric("percentage_used", "NVMe istrošenost (percentage used)", "%", "max", "percentage_used"),
    "available_spare": Metric("available_spare", "NVMe rezerva (available spare)", "%", "min", "available_spare"),
    "ssd_life_left": Metric("ssd_life_left", "Preostali vek SSD-a", "%", "min", "ssd_life_left"),
    "data_units_written": Metric("data_units_written", "Upisano (NVMe data units)", "B", "max", "data_units_written"),
    "total_lbas_written": Metric("total_lbas_written", "Upisano (Total LBAs Written)", "LBA", "max", "total_lbas_written"),
}

POOL_METRICS: dict[str, Metric] = {
    "used_bytes": Metric("used_bytes", "Zauzeto", "B", "max", "used_bytes"),
    "free_bytes": Metric("free_bytes", "Slobodno", "B", "min", "free_bytes"),
    "read_errors": Metric("read_errors", "READ greške", "", "max", "read_errors", "counter"),
    "write_errors": Metric("write_errors", "WRITE greške", "", "max", "write_errors", "counter"),
    "checksum_errors": Metric("checksum_errors", "CKSUM greške", "", "max", "checksum_errors", "counter"),
    "scan_progress": Metric("scan_progress", "Napredak scrub/resilver", "%", "max", None),
}

BUCKETS = ("raw", "hour", "day", "week")
MAX_RAW_POINTS = 5000


def auto_bucket(start: datetime, end: datetime) -> str:
    span = end - start
    if span <= timedelta(days=2):
        return "raw"
    if span <= timedelta(days=31):
        return "hour"
    if span <= timedelta(days=400):
        return "day"
    return "week"


async def _tz(db: AsyncSession) -> str:
    return await settings_store.get_setting(db, settings_store.TIMEZONE)


def _bucket_expr(bucket: str, column: str = "collected_at") -> str:
    if bucket == "raw":
        return column
    return f"date_trunc('{bucket}', {column} AT TIME ZONE :tz) AT TIME ZONE :tz"


async def series(
    db: AsyncSession,
    table: str,
    id_column: str,
    ids: list[int],
    metric: Metric,
    start: datetime,
    end: datetime,
    bucket: str,
) -> dict[int, list[dict[str, Any]]]:
    """Serija po entitetu: [{t, value, min, max, n}]. Za dane/nedelje van sirovih merenja koristi dnevni agregat."""
    tz = await _tz(db)
    col = metric.column
    agg = metric.agg
    params = {"ids": ids, "start": start, "end": end, "tz": tz}
    if bucket == "raw":
        sql = (
            f"SELECT {id_column} AS id, collected_at AS t, {col}::float AS value, {col}::float AS min, "
            f"{col}::float AS max, 1 AS n FROM {table} "
            f"WHERE {id_column} = ANY(:ids) AND collected_at BETWEEN :start AND :end AND {col} IS NOT NULL "
            f"ORDER BY collected_at LIMIT {MAX_RAW_POINTS * max(1, len(ids))}"
        )
    else:
        b = _bucket_expr(bucket)
        sql = (
            f"SELECT {id_column} AS id, {b} AS t, {agg}({col})::float AS value, min({col})::float AS min, "
            f"max({col})::float AS max, count({col}) AS n FROM {table} "
            f"WHERE {id_column} = ANY(:ids) AND collected_at BETWEEN :start AND :end AND {col} IS NOT NULL "
            f"GROUP BY 1, 2 ORDER BY 2"
        )
    rows = (await db.execute(text(sql), params)).mappings().all()
    result: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
    for r in rows:
        result[r["id"]].append({"t": r["t"], "value": r["value"], "min": r["min"], "max": r["max"], "n": r["n"]})

    # Stariji periodi postoje samo kao dnevni agregati (sirova merenja su obrisana po politici čuvanja).
    daily_table = {"disk_samples": "disk_daily", "pool_samples": "pool_daily"}[table]
    daily_id = {"disk_samples": "disk_id", "pool_samples": "pool_id"}[table]
    if bucket in ("day", "week") and metric.daily:
        unit = bucket
        dcol = metric.daily
        sql = (
            f"SELECT {daily_id} AS id, date_trunc('{unit}', day::timestamp) AT TIME ZONE :tz AS t, "
            f"{'avg' if agg == 'avg' else agg}({dcol})::float AS value, min({dcol})::float AS min, "
            f"max({dcol})::float AS max, sum(samples) AS n FROM {daily_table} "
            f"WHERE {daily_id} = ANY(:ids) AND day BETWEEN (:start AT TIME ZONE :tz)::date AND (:end AT TIME ZONE :tz)::date "
            f"AND {dcol} IS NOT NULL GROUP BY 1, 2 ORDER BY 2"
        )
        for r in (await db.execute(text(sql), params)).mappings().all():
            points = result[r["id"]]
            if not any(p["t"] == r["t"] for p in points):
                points.append({"t": r["t"], "value": r["value"], "min": r["min"], "max": r["max"], "n": r["n"]})
        for points in result.values():
            points.sort(key=lambda p: p["t"])
    return result


async def metric_stats(
    db: AsyncSession, table: str, id_column: str, entity_id: int, metric: Metric, start: datetime, end: datetime
) -> dict[str, Any]:
    """Min/max/prosek, prva/prethodna/poslednja vrednost, promena i brzina promene po danu u periodu."""
    col = metric.column
    sql = f"""
        WITH s AS (
            SELECT collected_at, {col}::float AS v FROM {table}
            WHERE {id_column} = :id AND collected_at BETWEEN :start AND :end AND {col} IS NOT NULL
        ), ordered AS (
            SELECT collected_at, v, row_number() OVER (ORDER BY collected_at DESC) AS rn_desc,
                   row_number() OVER (ORDER BY collected_at) AS rn_asc FROM s
        )
        SELECT (SELECT min(v) FROM s) AS min, (SELECT max(v) FROM s) AS max, (SELECT avg(v) FROM s) AS avg,
               (SELECT count(*) FROM s) AS n,
               (SELECT v FROM ordered WHERE rn_asc = 1) AS first, (SELECT collected_at FROM ordered WHERE rn_asc = 1) AS first_at,
               (SELECT v FROM ordered WHERE rn_desc = 1) AS last, (SELECT collected_at FROM ordered WHERE rn_desc = 1) AS last_at,
               (SELECT v FROM ordered WHERE rn_desc = 2) AS previous
    """
    r = (await db.execute(text(sql), {"id": entity_id, "start": start, "end": end})).mappings().one()
    data = dict(r)
    delta = None
    rate = None
    if r["first"] is not None and r["last"] is not None:
        delta = r["last"] - r["first"]
        days = (r["last_at"] - r["first_at"]).total_seconds() / 86400
        rate = delta / days if days >= 1 / 24 else None
    data.update({"metric": metric.column, "label": metric.label, "unit": metric.unit, "kind": metric.kind,
                 "delta": delta, "rate_per_day": rate})
    return data


async def disk_trends(db: AsyncSession, disk_id: int, metrics: list[str]) -> dict[str, dict[str, Any]]:
    """Promena ključnih vrednosti za poslednjih 24 h, 7 dana i 30 dana (spec. §8.3, §21.4 tačka 5)."""
    now = datetime.now().astimezone()
    windows = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
    result: dict[str, dict[str, Any]] = {}
    for name in metrics:
        metric = DISK_METRICS[name]
        result[name] = {"label": metric.label, "unit": metric.unit, "kind": metric.kind}
        for key, span in windows.items():
            stats = await metric_stats(db, "disk_samples", "disk_id", disk_id, metric, now - span, now)
            result[name][key] = {
                "delta": stats["delta"],
                "first": stats["first"],
                "last": stats["last"],
                "first_at": stats["first_at"],
                "covered_hours": ((stats["last_at"] - stats["first_at"]).total_seconds() / 3600)
                if stats["first_at"] and stats["last_at"] else None,
            }
    return result


async def availability(db: AsyncSession, device_ids: list[int], start: datetime, end: datetime, bucket: str) -> dict[str, Any]:
    """Dostupnost uređaja iz istorije ciklusa: uspešni/neuspešni po intervalu i periodi nedostupnosti.

    Nedostupnost počinje prvim neuspelim ciklusom posle uspešnog, a završava se prvim sledećim uspešnim.
    Testovi konekcije se ne računaju. Delimično uspešan ciklus znači da je uređaj dostupan.
    """
    tz = await _tz(db)
    b = "date_trunc('%s', started_at AT TIME ZONE :tz) AT TIME ZONE :tz" % (bucket if bucket != "raw" else "hour")
    params = {"ids": device_ids, "start": start, "end": end, "tz": tz}
    rows = (await db.execute(text(f"""
        SELECT device_id AS id, {b} AS t,
               count(*) FILTER (WHERE status IN ('success', 'partial')) AS ok,
               count(*) FILTER (WHERE status = 'failed') AS failed
        FROM collection_runs
        WHERE device_id = ANY(:ids) AND trigger <> 'test' AND status <> 'running'
          AND started_at BETWEEN :start AND :end
        GROUP BY 1, 2 ORDER BY 2
    """), params)).mappings().all()
    buckets: dict[int, list[dict[str, Any]]] = {i: [] for i in device_ids}
    for r in rows:
        buckets[r["id"]].append({"t": r["t"], "ok": r["ok"], "failed": r["failed"]})

    runs = (await db.execute(text("""
        SELECT device_id, started_at, status, error_message FROM collection_runs
        WHERE device_id = ANY(:ids) AND trigger <> 'test' AND status <> 'running'
          AND started_at BETWEEN :start AND :end
        ORDER BY device_id, started_at
    """), params)).mappings().all()
    outages: dict[int, list[dict[str, Any]]] = {i: [] for i in device_ids}
    totals: dict[int, dict[str, Any]] = {i: {"runs": 0, "ok": 0, "failed": 0} for i in device_ids}
    open_outage: dict[int, dict[str, Any]] = {}
    for run in runs:
        dev = run["device_id"]
        totals[dev]["runs"] += 1
        if run["status"] == "failed":
            totals[dev]["failed"] += 1
            if dev not in open_outage:
                open_outage[dev] = {"start": run["started_at"], "end": None, "failed_runs": 0,
                                    "reason": run["error_message"]}
            open_outage[dev]["failed_runs"] += 1
        else:
            totals[dev]["ok"] += 1
            if dev in open_outage:
                outage = open_outage.pop(dev)
                outage["end"] = run["started_at"]
                outages[dev].append(outage)
    now = datetime.now().astimezone()
    for dev, outage in open_outage.items():
        outages[dev].append(outage)  # i dalje traje
    for dev in device_ids:
        for outage in outages[dev]:
            outage["duration_seconds"] = ((outage["end"] or min(now, end)) - outage["start"]).total_seconds()
        t = totals[dev]
        t["availability_percent"] = round(100 * t["ok"] / t["runs"], 2) if t["runs"] else None
        t["outages"] = len(outages[dev])
        t["outage_seconds"] = sum(o["duration_seconds"] for o in outages[dev])
        t["longest_outage_seconds"] = max((o["duration_seconds"] for o in outages[dev]), default=0)
    return {"buckets": buckets, "outages": outages, "totals": totals}


async def aggregate_daily(db: AsyncSession) -> None:
    """Upisuje dnevne agregate za završene dane (i ponovo za poslednja 2 dana, zbog kasnih upisa)."""
    tz = await _tz(db)
    params = {"tz": tz}
    await db.execute(text("""
        INSERT INTO disk_daily (disk_id, day, samples, smart_failed_samples, temperature_min, temperature_max,
            temperature_avg, power_on_hours, power_cycles, reallocated_sectors, pending_sectors, uncorrectable_sectors,
            crc_errors, reported_uncorrect, media_errors, error_log_entries, unsafe_shutdowns, percentage_used,
            available_spare, ssd_life_left, data_units_written, total_lbas_written)
        SELECT disk_id, (collected_at AT TIME ZONE :tz)::date AS day, count(*),
            count(*) FILTER (WHERE smart_health = 'failed'), min(temperature_c), max(temperature_c), avg(temperature_c),
            max(power_on_hours), max(power_cycles), max(reallocated_sectors), max(pending_sectors),
            max(uncorrectable_sectors), max(crc_errors), max(reported_uncorrect), max(media_errors),
            max(error_log_entries), max(unsafe_shutdowns), max(percentage_used), min(available_spare),
            min(ssd_life_left), max(data_units_written), max(total_lbas_written)
        FROM disk_samples
        WHERE (collected_at AT TIME ZONE :tz)::date < (now() AT TIME ZONE :tz)::date
          AND (collected_at AT TIME ZONE :tz)::date >= coalesce((SELECT max(day) FROM disk_daily) - 2, '-infinity'::date)
        GROUP BY 1, 2
        ON CONFLICT (disk_id, day) DO UPDATE SET samples = EXCLUDED.samples,
            smart_failed_samples = EXCLUDED.smart_failed_samples, temperature_min = EXCLUDED.temperature_min,
            temperature_max = EXCLUDED.temperature_max, temperature_avg = EXCLUDED.temperature_avg,
            power_on_hours = EXCLUDED.power_on_hours, power_cycles = EXCLUDED.power_cycles,
            reallocated_sectors = EXCLUDED.reallocated_sectors, pending_sectors = EXCLUDED.pending_sectors,
            uncorrectable_sectors = EXCLUDED.uncorrectable_sectors, crc_errors = EXCLUDED.crc_errors,
            reported_uncorrect = EXCLUDED.reported_uncorrect, media_errors = EXCLUDED.media_errors,
            error_log_entries = EXCLUDED.error_log_entries, unsafe_shutdowns = EXCLUDED.unsafe_shutdowns,
            percentage_used = EXCLUDED.percentage_used, available_spare = EXCLUDED.available_spare,
            ssd_life_left = EXCLUDED.ssd_life_left, data_units_written = EXCLUDED.data_units_written,
            total_lbas_written = EXCLUDED.total_lbas_written
    """), params)
    await db.execute(text("""
        INSERT INTO pool_daily (pool_id, day, samples, unhealthy_samples, capacity_bytes, used_bytes, used_bytes_avg,
            free_bytes, read_errors, write_errors, checksum_errors)
        SELECT pool_id, (collected_at AT TIME ZONE :tz)::date, count(*), count(*) FILTER (WHERE healthy IS FALSE),
            max(capacity_bytes), max(used_bytes), avg(used_bytes), min(free_bytes), max(read_errors),
            max(write_errors), max(checksum_errors)
        FROM pool_samples
        WHERE (collected_at AT TIME ZONE :tz)::date < (now() AT TIME ZONE :tz)::date
          AND (collected_at AT TIME ZONE :tz)::date >= coalesce((SELECT max(day) FROM pool_daily) - 2, '-infinity'::date)
        GROUP BY 1, 2
        ON CONFLICT (pool_id, day) DO UPDATE SET samples = EXCLUDED.samples,
            unhealthy_samples = EXCLUDED.unhealthy_samples, capacity_bytes = EXCLUDED.capacity_bytes,
            used_bytes = EXCLUDED.used_bytes, used_bytes_avg = EXCLUDED.used_bytes_avg, free_bytes = EXCLUDED.free_bytes,
            read_errors = EXCLUDED.read_errors, write_errors = EXCLUDED.write_errors,
            checksum_errors = EXCLUDED.checksum_errors
    """), params)


# --- Prognoze (spec. §16.1): linearni trend iz istorije, uvek označen kao procena ---

PREDICT_DISK = {
    "percentage_used": ("NVMe istrošenost", "%", 100.0, "up"),
    "ssd_life_left": ("Preostali vek SSD-a", "%", 0.0, "down"),
    "available_spare": ("NVMe rezerva", "%", None, "down"),
    "reallocated_sectors": ("Realocirani sektori", "", None, "up"),
    "pending_sectors": ("Pending sektori", "", None, "up"),
    "temperature_c": ("Temperatura", "°C", None, "up"),
}


def _quality(n: int, span_days: float, r2: float | None) -> tuple[str, str]:
    if n < 10 or span_days < 7:
        return "low", f"Malo podataka ({n} očitavanja za {span_days:.1f} dana) – procena nije pouzdana."
    if r2 is not None and r2 < 0.5:
        return "medium", f"Vrednosti nisu ravnomerne (R² = {r2:.2f}) – trend je okviran."
    return "good", f"{n} očitavanja za {span_days:.0f} dana" + (f", R² = {r2:.2f}" if r2 is not None else "") + "."


async def predictions(db: AsyncSession, days: int = 90) -> dict[str, Any]:
    """Nagib (po danu) i procena dostizanja granice za diskove i pool-ove. Regresija se računa u bazi."""
    since = datetime.now().astimezone() - timedelta(days=days)
    disk_rows = []
    for col, (label, unit, limit, direction) in PREDICT_DISK.items():
        rows = (await db.execute(text(f"""
            SELECT s.disk_id, regr_slope(s.{col}, extract(epoch FROM s.collected_at) / 86400.0) AS slope,
                   regr_r2(s.{col}, extract(epoch FROM s.collected_at) / 86400.0) AS r2, count(s.{col}) AS n,
                   extract(epoch FROM max(s.collected_at) - min(s.collected_at)) / 86400.0 AS span,
                   (array_agg(s.{col} ORDER BY s.collected_at DESC))[1] AS last
            FROM disk_samples s JOIN disks d ON d.id = s.disk_id
            WHERE s.collected_at >= :since AND s.{col} IS NOT NULL AND d.is_present
            GROUP BY s.disk_id HAVING count(s.{col}) >= 2
        """), {"since": since})).mappings().all()
        for r in rows:
            slope = float(r["slope"]) if r["slope"] is not None else 0.0
            if col != "temperature_c" and abs(slope) < 1e-9 and limit is None:
                continue  # stabilni brojači nemaju šta da se prognozira
            eta = None
            if limit is not None and r["last"] is not None and slope != 0:
                remaining = (limit - float(r["last"])) / slope
                eta = remaining if remaining > 0 else None
            quality, note = _quality(r["n"], float(r["span"] or 0), float(r["r2"]) if r["r2"] is not None else None)
            disk_rows.append({
                "disk_id": r["disk_id"], "metric": col, "label": label, "unit": unit, "direction": direction,
                "last": r["last"], "slope_per_day": slope, "slope_per_30d": slope * 30, "limit": limit,
                "days_to_limit": eta, "quality": quality, "quality_note": note, "samples": r["n"],
                "span_days": float(r["span"] or 0),
            })
    pool_rows = []
    rows = (await db.execute(text("""
        SELECT s.pool_id, regr_slope(s.used_bytes, extract(epoch FROM s.collected_at) / 86400.0) AS slope,
               regr_r2(s.used_bytes, extract(epoch FROM s.collected_at) / 86400.0) AS r2, count(s.used_bytes) AS n,
               extract(epoch FROM max(s.collected_at) - min(s.collected_at)) / 86400.0 AS span
        FROM pool_samples s JOIN storage_pools p ON p.id = s.pool_id
        WHERE s.collected_at >= :since AND s.used_bytes IS NOT NULL AND p.is_present AND p.technology <> 'lvm_vg'
        GROUP BY s.pool_id HAVING count(s.used_bytes) >= 2
    """), {"since": since})).mappings().all()
    for r in rows:
        slope = float(r["slope"] or 0)
        quality, note = _quality(r["n"], float(r["span"] or 0), float(r["r2"]) if r["r2"] is not None else None)
        pool_rows.append({"pool_id": r["pool_id"], "slope_bytes_per_day": slope, "quality": quality,
                          "quality_note": note, "samples": r["n"], "span_days": float(r["span"] or 0)})
    return {"days": days, "disks": disk_rows, "pools": pool_rows}
