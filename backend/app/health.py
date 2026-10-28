"""Procena stanja: uslovi alarma i „Zdravlje diska” (spec. §8, §11).

Iz istorije očitavanja pravi listu uslova (Condition). Ista lista daje i alarme (events.py) i zdravlje diska,
pa se prikaz zdravlja i alarmi nikad ne razilaze. SMART PASSED nikad sam po sebi ne znači „Odlično”.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CollectionRun, Device, Disk, DiskSample, StoragePool, utcnow

SEVERITIES = ("info", "warning", "high", "critical")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}

HEALTH_LEVELS = ("excellent", "good", "attention", "endangered", "critical", "unknown")
# Najveća ozbiljnost uslova na disku → nivo zdravlja
LEVEL_BY_SEVERITY = {None: "excellent", "info": "good", "warning": "attention", "high": "endangered", "critical": "critical"}
PENALTY = {"info": 5, "warning": 20, "high": 40, "critical": 70}

RECOMMENDATIONS = {
    "attention": ["Pratiti disk: proveriti trend u narednim danima.", "Proveriti da li postoji ažurna rezervna kopija."],
    "endangered": [
        "Ne koristiti disk za nove kritične podatke.",
        "Pripremiti zamenski disk.",
        "Pokrenuti ili proveriti rezervnu kopiju.",
    ],
    "critical": [
        "Odmah proveriti rezervnu kopiju podataka.",
        "Zameniti disk što pre (ručno, kroz sistem uređaja – aplikacija ništa ne menja na skladištu).",
        "Ako je disk u ZFS/RAID nizu, pratiti resilver/rebuild posle zamene.",
    ],
    "unknown": ["Proveriti zašto podaci nisu dostupni (veza, SMART podrška, kontroler)."],
}

# Podrazumevani pragovi (spec. §11.2: konzervativni, označeni kao preporučeni, administrator ih menja).
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "temperature": {
        "hdd": {"info": 47, "warning": 50, "critical": 55},
        "ssd": {"info": 57, "warning": 60, "critical": 70},
        "nvme": {"info": 67, "warning": 70, "critical": 80},
    },
    "temperature_repeat_count": 3,  # prekoračenja upozoravajućeg praga u 24 h → visoko
    "temperature_hysteresis": 2,  # alarm se zatvara tek kada temperatura padne ispod praga − histereza
    "temperature_jump": 10,  # porast u odnosu na minimum poslednja 24 h → informativno
    "reallocated_high_24h": 5,
    "reallocated_high_7d": 10,
    "reallocated_high_30d": 20,
    "pending_high_24h": 2,
    "uncorrectable_critical_24h": 2,
    "crc_warning_24h": 10,
    "percentage_used": {"warning": 80, "high": 90, "critical": 100},
    "available_spare_min": 10,
    "ssd_life_left": {"warning": 20, "high": 10},
    "pool_usage": {"warning": 80, "high": 90, "critical": 95},
    "unreachable_runs": 2,
    "partial_runs": 3,
    "no_data_runs": 3,
    "confirmations": 1,  # koliko uzastopnih procena mora potvrditi uslov pre otvaranja alarma
    "cooldown_minutes": 60,
    "renotify_hours": 24,
}


def merge_thresholds(stored: dict[str, Any] | None) -> dict[str, Any]:
    result = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THRESHOLDS.items()}
    result["temperature"] = {k: dict(v) for k, v in DEFAULT_THRESHOLDS["temperature"].items()}
    for key, value in (stored or {}).items():
        if key not in result:
            continue
        if key == "temperature" and isinstance(value, dict):
            for t, limits in value.items():
                if t in result["temperature"] and isinstance(limits, dict):
                    result["temperature"][t].update({k: v for k, v in limits.items() if k in ("info", "warning", "critical")})
        elif isinstance(result[key], dict) and isinstance(value, dict):
            result[key].update({k: v for k, v in value.items() if k in result[key]})
        else:
            result[key] = value
    return result


@dataclass
class Condition:
    fingerprint: str
    severity: str
    category: str
    rule: str
    title: str
    message: str
    device_id: int
    disk_id: int | None = None
    pool_id: int | None = None
    metric: str | None = None
    previous_value: float | None = None
    current_value: float | None = None
    period: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiskHealth:
    level: str
    score: int | None
    reasons: list[dict[str, Any]]
    recommendations: list[str]


@dataclass
class Evaluation:
    conditions: list[Condition]
    health: dict[int, DiskHealth]
    rules: set[str]  # pravila koja su u ovoj proceni stvarno provereni (samo ona smeju automatski da zatvore alarm)


COUNTERS = ["reallocated_sectors", "pending_sectors", "uncorrectable_sectors", "reported_uncorrect", "crc_errors",
            "media_errors", "error_log_entries", "unsafe_shutdowns", "available_spare", "percentage_used",
            "ssd_life_left", "warning_temp_time", "critical_temp_time"]


def _temp_class(disk_type: str) -> str:
    return "nvme" if disk_type == "nvme" else ("ssd" if disk_type == "ssd" else "hdd")


async def _history(db: AsyncSession, disk_ids: list[int], now: datetime) -> dict[int, dict[str, Any]]:
    """Za svaki disk: prva vrednost brojača u prozorima 24 h / 7 d / 30 d, prethodna i prva ikad, temperature 24 h."""
    if not disk_ids:
        return {}
    parts = []
    for col in COUNTERS:
        for name, since in (("d1", ":s1"), ("d7", ":s7"), ("d30", ":s30")):
            parts.append(f"(array_agg({col} ORDER BY collected_at) FILTER (WHERE collected_at >= {since} AND {col} IS NOT NULL))[1] AS {col}__{name}")
        parts.append(f"max({col}) FILTER (WHERE rn = 2) AS {col}__prev")
    sql = f"""
        WITH s AS (
            SELECT *, row_number() OVER (PARTITION BY disk_id ORDER BY collected_at DESC) AS rn
            FROM disk_samples WHERE disk_id = ANY(:ids) AND collected_at >= :s30 AND smart_available
        )
        SELECT disk_id, min(collected_at) AS first_at, {", ".join(parts)},
               array_agg(temperature_c ORDER BY collected_at) FILTER (WHERE collected_at >= :s1 AND temperature_c IS NOT NULL) AS temps_24h
        FROM s GROUP BY disk_id
    """
    params = {"ids": disk_ids, "s1": now - timedelta(hours=24), "s7": now - timedelta(days=7), "s30": now - timedelta(days=30)}
    result: dict[int, dict[str, Any]] = {}
    for row in (await db.execute(text(sql), params)).mappings():
        result[row["disk_id"]] = dict(row)
    firsts = await db.execute(text(f"""
        SELECT DISTINCT ON (disk_id) disk_id, collected_at, {", ".join(COUNTERS)} FROM disk_samples
        WHERE disk_id = ANY(:ids) AND smart_available ORDER BY disk_id, collected_at
    """), {"ids": disk_ids})
    for row in firsts.mappings():
        result.setdefault(row["disk_id"], {})["first_ever"] = dict(row)
    recent = await db.execute(text("""
        SELECT disk_id, array_agg(smart_available ORDER BY collected_at DESC) AS avail FROM (
            SELECT disk_id, smart_available, collected_at,
                   row_number() OVER (PARTITION BY disk_id ORDER BY collected_at DESC) AS rn
            FROM disk_samples WHERE disk_id = ANY(:ids)
        ) x WHERE rn <= 10 GROUP BY disk_id
    """), {"ids": disk_ids})
    for row in recent.mappings():
        result.setdefault(row["disk_id"], {})["recent_available"] = row["avail"]
    return result


def _delta(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None:
        return None
    return cur - base


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}".replace(".", ",")


def _disk_name(disk: Disk) -> str:
    return f"{disk.device_path} ({disk.model or 'nepoznat model'})"


def evaluate_disk(device: Device, disk: Disk, sample: DiskSample | None, last_smart: DiskSample | None,
                  hist: dict[str, Any], th: dict[str, Any], open_fps: set[str],
                  nvme_critical_temp: float | None = None) -> list[Condition]:
    """Uslovi za jedan disk. `sample` je poslednje očitavanje, `last_smart` poslednje sa SMART podacima."""
    out: list[Condition] = []
    name = _disk_name(disk)
    dev = device.name

    def add(rule: str, severity: str, category: str, title: str, message: str, **kw: Any) -> None:
        out.append(Condition(f"disk:{disk.id}:{rule}", severity, category, rule, f"{dev}: {title}", message,
                             device.id, disk.id, **kw))

    if not disk.is_present:
        add("disk_missing", "high", "inventory", f"disk {disk.device_path} je nestao",
            f"Disk {name} nije pronađen u poslednjem ciklusu (poslednji put viđen {disk.last_seen_at:%d.%m.%Y. %H:%M} UTC). "
            "Proveriti da li je disk izvađen, otkazao ili ga kontroler više ne vidi.")
        return out

    s = last_smart if (sample is not None and sample.smart_health == "standby" and last_smart is not None) else sample
    recent = hist.get("recent_available") or []
    if sample is not None and not sample.smart_available and sample.smart_health != "standby":
        missing = 0
        for available in recent:
            if available:
                break
            missing += 1
        if missing >= th["no_data_runs"]:
            add("no_data", "warning", "data", f"nema SMART podataka za {disk.device_path}",
                f"Za disk {name} SMART podaci nisu dostupni već {missing} uzastopnih ciklusa. "
                f"Razlog: {sample.smart_message or 'nepoznat'}. To nije isto što i ispravan disk.",
                details={"cycles": missing})
    if s is None or not s.smart_available:
        return out

    if s.smart_health == "failed":
        add("smart_failed", "critical", "smart", f"SMART FAILED na {disk.device_path}",
            f"Disk {name} prijavljuje SMART overall-health: FAILED. Disk sam predviđa kvar.")

    # Brojači koji kod ispravnog diska ne rastu
    def growth(col: str) -> tuple[float | None, float | None, float | None, float | None]:
        cur = getattr(s, col)
        return cur, _delta(cur, hist.get(f"{col}__d1")), _delta(cur, hist.get(f"{col}__d7")), _delta(cur, hist.get(f"{col}__d30"))

    cur, d1, d7, d30 = growth("reallocated_sectors")
    if cur is not None and cur > 0:
        first = (hist.get("first_ever") or {}).get("reallocated_sectors")
        if (d1 or 0) >= th["reallocated_high_24h"] or (d7 or 0) >= th["reallocated_high_7d"] or (d30 or 0) >= th["reallocated_high_30d"]:
            sev, what = "high", "ubrzan rast realociranih sektora"
        elif (d1 or 0) > 0 or (d7 or 0) > 0:
            sev, what = "warning", "rast realociranih sektora"
        else:
            sev, what = "info", "realocirani sektori (stabilno)"
        add("reallocated", sev, "smart", f"{what} na {disk.device_path}",
            f"Realocirani sektori: {_fmt(cur)} (24 h: +{_fmt(d1 or 0)}, 7 dana: +{_fmt(d7 or 0)}, 30 dana: +{_fmt(d30 or 0)}"
            + (f"; prvo očitavanje: {_fmt(first)}" if first is not None else "") + ").",
            metric="reallocated_sectors", previous_value=hist.get("reallocated_sectors__prev"), current_value=cur,
            period="24h/7d/30d", details={"delta_24h": d1, "delta_7d": d7, "delta_30d": d30})

    cur, d1, d7, _ = growth("pending_sectors")
    if cur is not None and cur > 0:
        sev = "high" if (d1 or 0) >= th["pending_high_24h"] or (d7 or 0) >= th["pending_high_24h"] * 2 else "warning"
        add("pending", sev, "smart", f"sektori na čekanju (pending) na {disk.device_path}",
            f"Pending sektori: {_fmt(cur)} (24 h: +{_fmt(d1 or 0)}, 7 dana: +{_fmt(d7 or 0)}). Disk ne može pouzdano da pročita ove sektore.",
            metric="pending_sectors", previous_value=hist.get("pending_sectors__prev"), current_value=cur, period="24h/7d",
            details={"delta_24h": d1, "delta_7d": d7})

    for col, label in (("uncorrectable_sectors", "neispravljivi sektori"), ("reported_uncorrect", "prijavljene neispravljive greške")):
        cur, d1, d7, _ = growth(col)
        if cur is not None and cur > 0:
            sev = "critical" if (d1 or 0) >= th["uncorrectable_critical_24h"] else "high"
            add(col, sev, "smart", f"{label} na {disk.device_path}",
                f"{label.capitalize()}: {_fmt(cur)} (24 h: +{_fmt(d1 or 0)}, 7 dana: +{_fmt(d7 or 0)}). Moguć gubitak podataka u pogođenim sektorima.",
                metric=col, previous_value=hist.get(f"{col}__prev"), current_value=cur, period="24h/7d",
                details={"delta_24h": d1, "delta_7d": d7})

    cur, d1, d7, _ = growth("crc_errors")
    if cur is not None and (d7 or 0) > 0:
        sev = "warning" if (d1 or 0) >= th["crc_warning_24h"] else "info"
        add("crc_errors", sev, "smart", f"nove CRC greške na {disk.device_path}",
            f"UDMA CRC greške: {_fmt(cur)} (24 h: +{_fmt(d1 or 0)}, 7 dana: +{_fmt(d7 or 0)}). Obično je uzrok kabl, konektor ili kontroler, a ne sam disk.",
            metric="crc_errors", current_value=cur, period="24h/7d")

    # NVMe
    if s.critical_warning:
        add("nvme_critical_warning", "critical", "nvme", f"NVMe Critical Warning na {disk.device_path}",
            f"NVMe disk {name} ima postavljen Critical Warning (vrednost {s.critical_warning}). Kontroler prijavljuje ozbiljan problem.",
            metric="critical_warning", current_value=s.critical_warning)
    cur, d1, d7, _ = growth("media_errors")
    if cur is not None and cur > 0:
        prev = hist.get("media_errors__prev")
        sev = "high" if (prev is not None and cur > prev) or (d7 or 0) > 0 else "warning"
        add("media_errors", sev, "nvme", f"NVMe media greške na {disk.device_path}",
            f"Media and Data Integrity Errors: {_fmt(cur)} (prethodno očitavanje: {_fmt(prev)}, 7 dana: +{_fmt(d7 or 0)}).",
            metric="media_errors", previous_value=prev, current_value=cur, period="7d")
    cur, d1, d7, _ = growth("error_log_entries")
    if cur is not None and (d7 or 0) > 0:
        add("nvme_error_log", "info", "nvme", f"novi unosi u NVMe logu grešaka na {disk.device_path}",
            f"Error Information Log Entries: {_fmt(cur)} (7 dana: +{_fmt(d7)}).", metric="error_log_entries", current_value=cur)
    cur, d1, d7, _ = growth("unsafe_shutdowns")
    if cur is not None and (d7 or 0) >= 2:
        add("unsafe_shutdowns", "info", "nvme", f"nebezbedna gašenja na {disk.device_path}",
            f"Unsafe Shutdowns: {_fmt(cur)} (7 dana: +{_fmt(d7)}). Moguća nestabilnost napajanja ili hosta.",
            metric="unsafe_shutdowns", current_value=cur)
    spare, spare_th = s.available_spare, s.available_spare_threshold
    if spare is not None:
        limit = max(spare_th or 0, th["available_spare_min"])
        _, _, d7, d30 = growth("available_spare")
        if spare <= limit:
            add("available_spare", "critical", "nvme", f"NVMe rezerva ispod praga na {disk.device_path}",
                f"Available Spare: {spare}% (prag: {limit}%). Disk troši poslednje rezervne blokove.",
                metric="available_spare", current_value=spare)
        elif (d30 or 0) < 0:
            add("available_spare", "warning", "nvme", f"smanjenje NVMe rezerve na {disk.device_path}",
                f"Available Spare: {spare}% ({_fmt(d30)} u 30 dana).", metric="available_spare", current_value=spare)
    used = s.percentage_used
    if used is not None:
        lim = th["percentage_used"]
        sev = "critical" if used >= lim["critical"] else "high" if used >= lim["high"] else "warning" if used >= lim["warning"] else None
        if sev:
            add("percentage_used", sev, "nvme", f"NVMe istrošenost {used}% na {disk.device_path}",
                f"Percentage Used: {used}% (pragovi: {lim['warning']}/{lim['high']}/{lim['critical']}%).",
                metric="percentage_used", current_value=used)
    life = s.ssd_life_left
    if life is not None:
        lim = th["ssd_life_left"]
        sev = "high" if life <= lim["high"] else "warning" if life <= lim["warning"] else None
        if sev:
            add("ssd_life_left", sev, "smart", f"preostali vek SSD-a {life}% na {disk.device_path}",
                f"Preostali vek SSD-a: {life}% (pragovi: {lim['warning']}/{lim['high']}%).", metric="ssd_life_left", current_value=life)

    # Temperatura (samo iz svežeg očitavanja – standby disk nema trenutnu temperaturu)
    if sample is not None and sample.smart_available and sample.temperature_c is not None:
        t = sample.temperature_c
        lim = dict(th["temperature"][_temp_class(disk.disk_type)])
        if nvme_critical_temp:
            lim["critical"] = min(lim["critical"], nvme_critical_temp)
        temps = hist.get("temps_24h") or []
        over = sum(1 for x in temps if x >= lim["warning"])
        fp = f"disk:{disk.id}:temperature"
        holding = fp in open_fps and t >= lim["warning"] - th["temperature_hysteresis"]
        throttled = (hist.get("critical_temp_time__d1") is not None and (s.critical_temp_time or 0) > hist["critical_temp_time__d1"])
        if t >= lim["critical"] or throttled:
            sev = "critical"
        elif t >= lim["warning"] and over >= th["temperature_repeat_count"]:
            sev = "high"
        elif t >= lim["warning"] or holding:
            sev = "warning"
        elif t >= lim["info"]:
            sev = "info"
        else:
            sev = None
        if sev:
            add("temperature", sev, "temperature", f"temperatura {t} °C na {disk.device_path}",
                f"Temperatura: {t} °C (pragovi za {_temp_class(disk.disk_type).upper()}: {lim['info']}/{lim['warning']}/{lim['critical']} °C). "
                f"Prekoračenja upozoravajućeg praga u 24 h: {over}." + (" Disk je ulazio u kritičnu temperaturu (throttling)." if throttled else ""),
                metric="temperature_c", current_value=t, period="24h", details={"exceedances_24h": over, "max_24h": max(temps, default=None)})
        if temps and t - min(temps) >= th["temperature_jump"]:
            add("temperature_jump", "info", "temperature", f"nagli rast temperature na {disk.device_path}",
                f"Temperatura je porasla sa {min(temps)} °C na {t} °C u poslednja 24 h.",
                metric="temperature_c", previous_value=min(temps), current_value=t, period="24h")
    return out


def disk_health(disk: Disk, sample: DiskSample | None, last_smart: DiskSample | None,
                conditions: list[Condition]) -> DiskHealth:
    own = [c for c in conditions if c.disk_id == disk.id]
    reasons = [{"severity": c.severity, "rule": c.rule, "text": c.message} for c in
               sorted(own, key=lambda c: -SEVERITY_RANK[c.severity])]
    effective = last_smart if (sample is not None and sample.smart_health == "standby" and last_smart) else sample
    if not disk.is_present:
        return DiskHealth("unknown", None, reasons or [{"severity": "high", "rule": "disk_missing", "text": "Disk nije pronađen."}],
                          RECOMMENDATIONS["unknown"])
    if effective is None or not effective.smart_available:
        why = (sample.smart_message if sample is not None else None) or "SMART podaci nisu dostupni."
        return DiskHealth("unknown", None, reasons + [{"severity": "info", "rule": "no_data", "text": why}], RECOMMENDATIONS["unknown"])
    worst = max((c.severity for c in own), key=lambda x: SEVERITY_RANK[x], default=None)
    level = LEVEL_BY_SEVERITY[worst]
    score = max(0, 100 - sum(PENALTY[c.severity] for c in own))
    if level == "excellent" and effective.power_on_hours and effective.power_on_hours > 50_000:
        level = "good"
        reasons.append({"severity": "info", "rule": "age", "text": f"Disk ima {effective.power_on_hours} radnih sati (preko 50.000) – očekivano habanje."})
        score = min(score, 90)
    if sample is not None and sample.smart_health == "standby":
        reasons.append({"severity": "info", "rule": "standby", "text": "Disk je u standby režimu; procena je po poslednjem SMART očitavanju."})
    return DiskHealth(level, score, reasons, RECOMMENDATIONS.get(level, []))


def evaluate_pool(device: Device, pool: StoragePool, th: dict[str, Any], open_fps: set[str]) -> list[Condition]:
    out: list[Condition] = []
    if not pool.is_present:
        return out
    tech_label = {"zfs": "ZFS pool", "mdadm": "RAID niz", "lvm_thin": "LVM thin pool", "lvm_vg": "LVM grupa",
                  "pve_storage": "Proxmox storage", "synology_volume": "volumen"}.get(pool.technology, pool.technology)

    def add(rule: str, severity: str, title: str, message: str, **kw: Any) -> None:
        out.append(Condition(f"pool:{pool.id}:{rule}", severity, "pool", rule, f"{device.name}: {title}", message,
                             device.id, pool_id=pool.id, **kw))

    if pool.healthy is False:
        status = (pool.status or "").upper()
        sev = "critical" if status in ("FAULTED", "UNAVAIL", "OFFLINE", "SUSPENDED") or pool.technology == "mdadm" else "high"
        bad = [m["name"] + (f" ({m.get('disk_path')})" if m.get("disk_path") else "") + f": {m.get('state')}"
               for m in pool.members or [] if m.get("kind") == "disk" and m.get("state") not in (None, "ONLINE", "AVAIL", "INUSE", "SPARE")]
        add("pool_unhealthy", sev, f"{tech_label} {pool.name} je {pool.status}",
            f"{tech_label} {pool.name} je u stanju {pool.status}." + (f" Članovi sa problemom: {', '.join(bad)}." if bad else "")
            + (f" {pool.message}" if pool.message else ""), details={"members": bad})
    errors = (pool.read_errors or 0) + (pool.write_errors or 0) + (pool.checksum_errors or 0)
    member_errors = sum((m.get("read_errors") or 0) + (m.get("write_errors") or 0) + (m.get("checksum_errors") or 0)
                        for m in pool.members or [])
    if errors or member_errors:
        add("pool_errors", "warning", f"greške u {pool.name}",
            f"{tech_label} {pool.name}: READ {pool.read_errors or 0}, WRITE {pool.write_errors or 0}, CKSUM {pool.checksum_errors or 0}"
            f" (zbir po članovima: {member_errors}).", metric="pool_errors", current_value=errors + member_errors)
    if pool.scan_state == "finished" and pool.scan_errors:
        add("scrub_errors", "high", f"scrub {pool.name} završen sa greškama",
            f"Poslednji {pool.scan_type or 'scrub'} na {pool.name} ({pool.scan_finished_at}) završen je sa {pool.scan_errors} grešaka.",
            metric="scan_errors", current_value=pool.scan_errors)
    if pool.technology != "lvm_vg" and pool.used_bytes is not None and pool.capacity_bytes:
        pct = 100 * pool.used_bytes / pool.capacity_bytes
        lim = th["pool_usage"]
        sev = "critical" if pct >= lim["critical"] else "high" if pct >= lim["high"] else "warning" if pct >= lim["warning"] else None
        if sev:
            add("pool_usage", sev, f"{pool.name} je popunjen {pct:.0f}%",
                f"{tech_label} {pool.name}: zauzeto {pct:.1f}% (pragovi {lim['warning']}/{lim['high']}/{lim['critical']}%).",
                metric="used_percent", current_value=round(pct, 1))
    return out


def correlate(device: Device, pools: list[StoragePool], conditions: list[Condition], disks: dict[int, Disk]) -> list[Condition]:
    """ZFS/RAID korelacija (spec. §8.7): disk sa SMART problemom u degradiranom nizu → kritično."""
    out: list[Condition] = []
    disk_problem = {}
    for c in conditions:
        if c.disk_id and c.category in ("smart", "nvme", "inventory") and SEVERITY_RANK[c.severity] >= SEVERITY_RANK["warning"]:
            disk_problem.setdefault(c.disk_id, []).append(c)
    for pool in pools:
        if pool.healthy is not False or not pool.is_present:
            continue
        for member in pool.members or []:
            disk_id = member.get("disk_id")
            if not disk_id or disk_id not in disk_problem or disk_id not in disks:
                continue
            disk = disks[disk_id]
            problems = "; ".join(c.title.split(": ", 1)[-1] for c in disk_problem[disk_id])
            out.append(Condition(
                f"disk:{disk_id}:pool_correlation:{pool.id}", "critical", "pool", "pool_correlation",
                f"{device.name}: disk {disk.device_path} i degradiran {pool.name}",
                f"Disk {disk.device_path} ima SMART probleme ({problems}). Pool {pool.name} je u stanju {pool.status}, "
                f"a disk je deo pogođenog niza (član {member.get('name')}, stanje {member.get('state')}).",
                device.id, disk_id=disk_id, pool_id=pool.id,
            ))
    return out


async def device_conditions(db: AsyncSession, device: Device, th: dict[str, Any]) -> list[Condition]:
    """Dostupnost uređaja i kompletnost prikupljanja iz poslednjih ciklusa."""
    runs = list(await db.scalars(
        select(CollectionRun).where(CollectionRun.device_id == device.id, CollectionRun.trigger != "test",
                                    CollectionRun.status != "running")
        .order_by(CollectionRun.started_at.desc()).limit(max(th["unreachable_runs"], th["partial_runs"]) + 1)
    ))
    out: list[Condition] = []
    failed = 0
    for run in runs:
        if run.status != "failed":
            break
        failed += 1
    if failed >= th["unreachable_runs"]:
        last = runs[0]
        out.append(Condition(f"device:{device.id}:unreachable", "high", "device", "device_unreachable",
                             f"{device.name}: uređaj nije dostupan",
                             f"Poslednjih {failed} ciklusa prikupljanja nije uspelo. Poslednja greška: {last.error_message}. "
                             "Nedostupan uređaj ne znači neispravan disk, ali podaci sada nisu ažurni.",
                             device.id, details={"failed_runs": failed, "error_kind": last.error_kind}))
    partial = 0
    for run in runs:
        if run.status != "partial":
            break
        partial += 1
    if partial >= th["partial_runs"]:
        out.append(Condition(f"device:{device.id}:partial", "warning", "data", "collection_partial",
                             f"{device.name}: prikupljanje je nepotpuno",
                             f"Poslednjih {partial} ciklusa je delimično uspelo: {runs[0].error_message}",
                             device.id, details={"partial_runs": partial}))
    return out


async def evaluate_device(db: AsyncSession, device: Device, th: dict[str, Any], open_fps: set[str],
                          collected: bool) -> Evaluation:
    """Kompletna procena uređaja. Kada ciklus nije uspeo (collected=False), proveravaju se samo pravila uređaja."""
    conditions = await device_conditions(db, device, th)
    rules = {"device_unreachable", "collection_partial"}
    health: dict[int, DiskHealth] = {}
    if not collected:
        return Evaluation(conditions, health, rules)

    from .routers.storage import last_smart_samples  # izbegava kružni import

    disks = {d.id: d for d in await db.scalars(select(Disk).where(Disk.device_id == device.id))}
    samples = {s.id: s for s in await db.scalars(
        select(DiskSample).where(DiskSample.id.in_([d.latest_sample_id for d in disks.values() if d.latest_sample_id]))
    )} if disks else {}
    latest = {d.id: samples.get(d.latest_sample_id) for d in disks.values()}
    last_smart = await last_smart_samples(db, [i for i, s in latest.items() if s is not None and s.smart_health == "standby"])
    hist = await _history(db, list(disks), utcnow())
    for disk in disks.values():
        nvme_crit = None
        raw = disk.last_raw or {}
        if disk.disk_type == "nvme":
            nvme_crit = (raw.get("temperature") or {}).get("critical_limit_max")
        conditions += evaluate_disk(device, disk, latest[disk.id], last_smart.get(disk.id), hist.get(disk.id, {}), th,
                                    open_fps, nvme_crit)
    pools = list(await db.scalars(select(StoragePool).where(StoragePool.device_id == device.id)))
    for pool in pools:
        conditions += evaluate_pool(device, pool, th, open_fps)
    conditions += correlate(device, pools, conditions, disks)
    for disk in disks.values():
        health[disk.id] = disk_health(disk, latest[disk.id], last_smart.get(disk.id), conditions)
    rules |= {"disk_missing", "no_data", "smart_failed", "reallocated", "pending", "uncorrectable_sectors",
              "reported_uncorrect", "crc_errors", "nvme_critical_warning", "media_errors", "nvme_error_log",
              "unsafe_shutdowns", "available_spare", "percentage_used", "ssd_life_left", "temperature",
              "temperature_jump", "pool_unhealthy", "pool_errors", "scrub_errors", "pool_usage", "pool_correlation"}
    return Evaluation(conditions, health, rules)
