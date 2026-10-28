"""Parsiranje stanja skladišta: ZFS (zpool), LVM/LVM-thin, Proxmox storage, mdadm i Synology volumeni."""

import json
import re
from typing import Any

from .model import PoolMember, PoolReading

# --- Imena diskova ---


def disk_key(path: str | None) -> str | None:
    """Svodi putanju diska ili particije na ime fizičkog diska: /dev/sda1 → sda, nvme0n1p2 → nvme0, ada0p2 → ada0."""
    if not path:
        return None
    name = path.rsplit("/", 1)[-1]
    m = re.match(r"^(nvme\d+)(?:n\d+)?(?:p\d+)?$", name)
    if m:
        return m.group(1)
    m = re.match(r"^nvd(\d+)(?:p\d+)?$", name)  # FreeBSD: nvd0 je namespace kontrolera nvme0
    if m:
        return f"nvme{m.group(1)}"
    m = re.match(r"^((?:sd|vd|xvd|hd)[a-z]+)\d*$", name)
    if m:
        return m.group(1)
    m = re.match(r"^((?:ada|da|nda|mfid|mfisyspd)\d+)(?:p\d+|s\d+[a-h]?)?$", name)
    if m:
        return m.group(1)
    m = re.match(r"^(sata\d+)(?:p\d+)?$", name)  # Synology DSM 7.2+
    if m:
        return m.group(1)
    return name


def parse_glabel(text: str) -> dict[str, str]:
    """FreeBSD `glabel status -s`: gptid/… → ada0p2."""
    labels = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            labels[parts[0]] = parts[-1]
    return labels


# --- ZFS ---


def parse_zpool_list(text: str) -> dict[str, dict[str, Any]]:
    """`zpool list -Hp -o name,size,alloc,free,frag,cap,health`."""
    pools = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 7:
            continue

        def num(value: str) -> int | None:
            return int(value) if value.isdigit() else None

        pools[parts[0]] = {
            "size": num(parts[1]),
            "alloc": num(parts[2]),
            "free": num(parts[3]),
            "frag": num(parts[4].rstrip("%")),
            "cap": num(parts[5].rstrip("%")),
            "health": parts[6],
        }
    return pools


_VDEV_RE = re.compile(r"^(mirror|raidz[123]?|draid[123]?[:\w]*|replacing|spare)-\d+$")
_GROUPS = {"logs", "cache", "spares", "special", "dedup"}


def _count(value: str) -> int | None:
    """Brojač grešaka iz zpool status (-p daje tačne brojeve, bez -p može biti „1.2K”)."""
    if value.isdigit():
        return int(value)
    m = re.match(r"^([\d.]+)([KMGT])$", value)
    if m:
        return int(float(m.group(1)) * {"K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}[m.group(2)])
    return None


def _parse_scan(text: str, pool: PoolReading) -> None:
    pool.scan_text = text or None
    if not text or text.startswith("none requested"):
        pool.scan_state = "none"
        return
    first = text.splitlines()[0]
    pool.scan_type = "resilver" if first.startswith("resilver") else ("scrub" if "scrub" in first else None)
    if "in progress" in first:
        pool.scan_state = "in_progress"
        m = re.search(r"([\d.]+)% done", text)
        pool.scan_progress = float(m.group(1)) if m else None
    elif "paused" in first:
        pool.scan_state = "paused"
    elif "canceled" in first:
        pool.scan_state = "canceled"
    else:
        pool.scan_state = "finished"
        m = re.search(r"with (\d+) errors? on (.+)$", first)
        if m:
            pool.scan_errors = int(m.group(1))
            pool.scan_finished_at = re.sub(r"\s+", " ", m.group(2)).strip()


def parse_zpool_status(text: str, labels: dict[str, str] | None = None) -> dict[str, PoolReading]:
    """Tekst `zpool status -p` (na Linuxu sa -P -L). Vraća pool → PoolReading (bez kapaciteta)."""
    labels = labels or {}
    pools: dict[str, PoolReading] = {}
    for block in re.split(r"(?m)^\s*pool: ", text)[1:]:
        lines = block.splitlines()
        name = lines[0].strip()
        fields: dict[str, list[str]] = {}
        config: list[str] = []
        current = None
        for line in lines[1:]:
            m = re.match(r"^\s*(state|status|action|scan|see|config|errors|remove|checkpoint):\s?(.*)$", line)
            if m and not line.startswith("\t\t") and (current != "config" or m.group(1) == "errors"):
                current = m.group(1)
                fields[current] = [m.group(2).strip()] if m.group(2).strip() else []
            elif current == "config":
                config.append(line)
            elif current is not None and line.strip():
                fields[current].append(line.strip())

        state = " ".join(fields.get("state", [])) or "UNKNOWN"
        pool = PoolReading(name=name, technology="zfs", status=state, healthy=None)
        pool.message = " ".join(fields.get("status", [])) or None
        pool.data_errors = " ".join(fields.get("errors", [])) or None
        _parse_scan("\n".join(fields.get("scan", [])), pool)
        _parse_config(config, pool, labels)

        problems = state != "ONLINE"
        if any((m.read_errors or 0) + (m.write_errors or 0) + (m.checksum_errors or 0) for m in pool.members):
            problems = True
        if (pool.read_errors or 0) + (pool.write_errors or 0) + (pool.checksum_errors or 0):
            problems = True
        if pool.data_errors and "No known data errors" not in pool.data_errors:
            problems = True
        pool.healthy = not problems
        pools[name] = pool
    return pools


def _parse_config(lines: list[str], pool: PoolReading, labels: dict[str, str]) -> None:
    rows = [line for line in lines if line.strip()]
    if rows and rows[0].split()[:2] == ["NAME", "STATE"]:
        rows = rows[1:]
    if not rows:
        return
    base = len(rows[0]) - len(rows[0].lstrip())
    top_level: list[str] = []
    group = None
    for row in rows:
        indent = (len(row) - len(row.lstrip()) - base) // 2
        parts = row.split()
        name = parts[0]
        state = parts[1] if len(parts) > 1 else None
        counters = [_count(p) for p in parts[2:5]] if len(parts) >= 5 else [None, None, None]
        note = " ".join(parts[5:]) if len(parts) > 5 else None
        if indent == 0 and name == pool.name:
            pool.read_errors, pool.write_errors, pool.checksum_errors = counters
            continue
        if indent == 0 and name in _GROUPS:
            group = name
            pool.members.append(PoolMember(name=name, kind="group", depth=0))
            continue
        if indent == 0:
            group = None
        kind = "vdev" if _VDEV_RE.match(name) else "disk"
        depth = indent if indent > 0 else 1
        if group is None and depth == 1:
            top_level.append(name.split("-")[0] if kind == "vdev" else "disk")
        disk_path = None
        if kind == "disk":
            resolved = labels.get(name.removeprefix("/dev/"), name)
            disk_path = disk_key(resolved)
        pool.members.append(PoolMember(
            name=name, state=state, read_errors=counters[0], write_errors=counters[1],
            checksum_errors=counters[2], disk_path=disk_path, kind=kind, depth=depth, note=note,
        ))

    if top_level:
        kinds = sorted(set(top_level))
        if kinds == ["disk"]:
            pool.redundancy = "stripe" if len(top_level) > 1 else "single"
        elif "disk" in kinds:
            pool.redundancy = "mešovito (" + ", ".join(k for k in kinds if k != "disk") + " + pojedinačni diskovi)"
        else:
            pool.redundancy = ", ".join(kinds) + (f" × {len(top_level)}" if len(top_level) > 1 else "")


def zfs_pools(list_text: str, status_text: str, labels: dict[str, str] | None = None) -> list[PoolReading]:
    capacities = parse_zpool_list(list_text)
    pools = parse_zpool_status(status_text, labels)
    for name, cap in capacities.items():
        pool = pools.get(name)
        if pool is None:
            pool = PoolReading(name=name, technology="zfs", status=cap["health"], healthy=cap["health"] == "ONLINE")
            pools[name] = pool
        pool.capacity_bytes = cap["size"]
        pool.used_bytes = cap["alloc"]
        pool.free_bytes = cap["free"]
        pool.details.update({"fragmentation_percent": cap["frag"], "capacity_percent": cap["cap"]})
    return list(pools.values())


# --- LVM ---


def _lvm_rows(text: str, key: str) -> list[dict[str, str]]:
    data = json.loads(text)
    rows: list[dict[str, str]] = []
    for report in data.get("report", []):
        rows.extend(report.get(key, []))
    return rows


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_LV_HEALTH = {"p": "partial", "r": "refresh needed", "m": "mismatches", "X": "unknown", "F": "failed",
              "D": "data space out", "M": "metadata read only", "E": "dm-writecache error"}


def lvm_pools(lvs_text: str, vgs_text: str) -> list[PoolReading]:
    pools: list[PoolReading] = []
    for vg in _lvm_rows(vgs_text, "vg"):
        attr = vg.get("vg_attr", "")
        partial = len(attr) > 3 and attr[3] == "p"
        size, free = _int(vg.get("vg_size")), _int(vg.get("vg_free"))
        pools.append(PoolReading(
            name=vg.get("vg_name", "?"), technology="lvm_vg",
            status="partial" if partial else "ok", healthy=not partial,
            capacity_bytes=size, free_bytes=free,
            used_bytes=size - free if size is not None and free is not None else None,
            message="Volume group je delimičan - nedostaje fizički volumen." if partial else None,
            details={"pv_count": _int(vg.get("pv_count")), "lv_count": _int(vg.get("lv_count")), "attr": attr},
        ))
    lvs = _lvm_rows(lvs_text, "lv")
    for lv in lvs:
        attr = lv.get("lv_attr", "")
        if not attr.startswith("t"):
            continue
        size = _int(lv.get("lv_size"))
        data_pct = _float(lv.get("data_percent"))
        meta_pct = _float(lv.get("metadata_percent"))
        health = attr[8] if len(attr) > 8 else "-"
        active = len(attr) > 4 and attr[4] == "a"
        problems = []
        if health != "-":
            problems.append(f"LVM stanje: {_LV_HEALTH.get(health, health)}")
        if data_pct is not None and data_pct >= 100:
            problems.append("Thin pool je pun (data 100%).")
        if meta_pct is not None and meta_pct >= 100:
            problems.append("Metapodaci thin pool-a su puni.")
        used = int(size * data_pct / 100) if size is not None and data_pct is not None else None
        name = f"{lv.get('vg_name')}/{lv.get('lv_name')}"
        thin_volumes = sum(1 for x in lvs if x.get("pool_lv") == lv.get("lv_name") and x.get("vg_name") == lv.get("vg_name"))
        pools.append(PoolReading(
            name=name, technology="lvm_thin",
            status=("active" if active else "inactive") if not problems else "problem",
            healthy=None if not active else not problems,
            capacity_bytes=size, used_bytes=used,
            free_bytes=size - used if size is not None and used is not None else None,
            message=" ".join(problems) or (None if active else "Thin pool nije aktivan."),
            details={"data_percent": data_pct, "metadata_percent": meta_pct, "attr": attr, "thin_volumes": thin_volumes},
        ))
    return pools


# --- Proxmox storage (pvesm status) ---


def pve_storages(text: str) -> list[PoolReading]:
    pools = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        name, stype, status = parts[0], parts[1], parts[2]
        total, used, avail = (_int(p) for p in parts[3:6])
        kib = 1024
        pools.append(PoolReading(
            name=name, technology="pve_storage", status=status,
            healthy=True if status == "active" else (None if status == "disabled" else False),
            capacity_bytes=total * kib if total is not None else None,
            used_bytes=used * kib if used is not None else None,
            free_bytes=avail * kib if avail is not None else None,
            message=None if status in ("active", "disabled") else "Proxmox storage nije aktivan (nedostupan).",
            details={"type": stype},
        ))
    return pools


# --- Linux softverski RAID (/proc/mdstat) ---


def parse_mdstat(text: str) -> list[PoolReading]:
    pools: list[PoolReading] = []
    current: PoolReading | None = None
    for line in text.splitlines():
        m = re.match(r"^(md\d+)\s*:\s*(\w+)\s+(?:\((\w[\w-]*)\)\s+)?(raid\d+|linear|multipath)?\s*(.*)$", line)
        if m:
            name, state, ro, level, members = m.groups()
            current = PoolReading(name=name, technology="mdadm", status=state, healthy=state == "active",
                                  redundancy=level)
            if ro:
                current.details["mode"] = ro
            for member in members.split():
                mm = re.match(r"^([\w-]+)\[(\d+)\](\(([FSWR])\))?$", member)
                if not mm:
                    continue
                flag = mm.group(4)
                member_state = {"F": "FAULTED", "S": "SPARE", "W": "WRITEMOSTLY", "R": "REPLACEMENT"}.get(flag or "", "ONLINE")
                current.members.append(PoolMember(name=mm.group(1), state=member_state,
                                                  disk_path=disk_key(mm.group(1)), depth=1))
                if flag == "F":
                    current.healthy = False
            pools.append(current)
            continue
        if current is None:
            continue
        m = re.search(r"(\d+) blocks.*\[(\d+)/(\d+)\]\s+\[([U_]+)\]", line)
        if m:
            current.capacity_bytes = int(m.group(1)) * 1024
            total, active = int(m.group(2)), int(m.group(3))
            current.details["devices"] = f"{active}/{total}"
            if active < total or "_" in m.group(4):
                current.healthy = False
                current.status = "degraded"
                current.message = f"RAID je degradiran: aktivno {active} od {total} diskova."
            continue
        m = re.search(r"(recovery|resync|check|reshape|repair)\s*=\s*([\d.]+)%", line)
        if m:
            current.scan_type = m.group(1)
            current.scan_state = "in_progress"
            current.scan_progress = float(m.group(2))
            current.scan_text = line.strip()
        if not line.strip():
            current = None
    return pools


# --- Synology volumeni (df) ---


def synology_volumes(df_text: str) -> list[PoolReading]:
    """`df -kP`: samo /volumeN tačke montiranja. Stanje RAID-a dolazi iz /proc/mdstat."""
    pools = []
    for line in df_text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6 or not re.match(r"^/volume\d+$", parts[5]):
            continue
        total, used, avail = (_int(p) for p in parts[1:4])
        pools.append(PoolReading(
            name=parts[5], technology="synology_volume", status="mounted", healthy=None,
            capacity_bytes=total * 1024 if total is not None else None,
            used_bytes=used * 1024 if used is not None else None,
            free_bytes=avail * 1024 if avail is not None else None,
            details={"filesystem": parts[0]},
        ))
    return pools
