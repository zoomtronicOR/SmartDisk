"""Platformski adapteri: koje read-only komande se izvršavaju na kojoj platformi i kako se rezultati spajaju.

Sve komande su fiksni šabloni. Jedine promenljive delove (putanja alata, ime diska i -d tip) daje sam uređaj
i oni se pre upotrebe proveravaju strogim regularnim izrazima, tako da ništa ne može da „pobegne” u shell.
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable

from ..ssh.client import CommandResult
from . import smart, storage
from .model import CollectResult, DiskReading

log = logging.getLogger("smartdisk.adapters")

Runner = Callable[[str], Awaitable[CommandResult]]

# -d tipovi koje aplikacija prosleđuje smartctl-u (isti spisak je u sudoers profilima).
SMART_TYPES = ("sat", "nvme", "scsi", "ata", "atacam", "auto")
_DEV_PATH = re.compile(r"^/dev/(sd[a-z]{1,2}|nvme\d{1,2}|ada\d{1,2}|da\d{1,2}|nda\d{1,2}|sata\d{1,2}|hd[a-z])$")
_TOOL_PATH = re.compile(r"^/[\w./-]+$")
_SKIP_DEVICES = re.compile(r"^/dev/(ses|pass|sg)\d+")

SUDO_HINT = (
    "Komanda zahteva sudo, a sudo nije podešen za namenski nalog (ili traži lozinku). "
    "Podesite sudoers profil iz dokumentacije."
)


class Context:
    def __init__(self, run: Runner, tools: dict[str, str | None], use_sudo: bool) -> None:
        self.run = run
        self.tools = {k: v for k, v in tools.items() if v and _TOOL_PATH.match(v)}
        self.use_sudo = use_sudo
        self.result = CollectResult()

    def tool(self, name: str) -> str | None:
        return self.tools.get(name)

    def privileged(self, command: str) -> str:
        return f"sudo -n {command}" if self.use_sudo else command

    async def call(self, command: str, what: str, ok_codes: tuple[int, ...] = (0,)) -> str | None:
        """Izvršava komandu; greška se beleži kao greška koraka, a ciklus se nastavlja."""
        res = await self.run(command)
        if res.exit_status in ok_codes:
            return res.stdout
        err = (res.stderr or "").strip()
        if "sudo" in err and ("password" in err or "not allowed" in err or "lozink" in err or "may not run" in err):
            self.result.errors.append(f"{what}: {SUDO_HINT}")
        elif "command not found" in err or "not found" in err:
            self.result.errors.append(f"{what}: komanda nije pronađena ({err[:200]}).")
        else:
            self.result.errors.append(f"{what}: komanda je vratila kod {res.exit_status}. {err[:300]}".strip())
        return None


# --- Diskovi i SMART ---


def parse_scan(stdout: str) -> list[tuple[str, str]]:
    """`smartctl --scan-open` (-j ili tekst) → [(putanja, -d tip)]."""
    found: list[tuple[str, str]] = []
    try:
        data = json.loads(stdout)
        entries = [(d.get("name", ""), d.get("type", "auto")) for d in data.get("devices", [])]
    except (ValueError, AttributeError):
        entries = []
        for line in stdout.splitlines():
            m = re.match(r"^(/dev/\S+)\s+-d\s+(\S+)", line)
            if m:
                entries.append((m.group(1), m.group(2)))
    for path, dtype in entries:
        if _SKIP_DEVICES.match(path):
            continue
        if not _DEV_PATH.match(path):
            log.info("Preskačem uređaj sa neočekivanim imenom: %r", path)
            continue
        found.append((path, dtype if dtype in SMART_TYPES else "auto"))
    return found


async def _smartctl_json_ok(ctx: Context) -> bool:
    """smartctl 7+ podržava -j. Stariji (npr. 6.5 na DSM-u) koristi tekstualni izlaz."""
    version = ctx.tools.get("smartctl_version") or ""
    m = re.search(r"smartctl (\d+)\.", version)
    return not m or int(m.group(1)) >= 7


async def collect_disks(ctx: Context, json_mode: bool = True) -> list[DiskReading]:
    smartctl = ctx.tool("smartctl")
    if not smartctl:
        ctx.result.errors.append("smartctl nije pronađen – SMART podaci nisu dostupni.")
        return []
    scan_cmd = f"{smartctl} -j --scan-open" if json_mode else f"{smartctl} --scan-open"
    out = await ctx.call(ctx.privileged(scan_cmd), "Pretraga diskova (smartctl --scan-open)")
    if out is None:
        return []
    ctx.result.disks_complete = True
    disks: list[DiskReading] = []
    for path, dtype in parse_scan(out):
        if json_mode:
            cmd = f"{smartctl} -j -a -n standby -d {dtype} {path}"
        else:
            cmd = f"{smartctl} -a -n standby -d {dtype} {path}"
        res = await ctx.run(ctx.privileged(cmd))
        err = (res.stderr or "").strip()
        if res.exit_status != 0 and not res.stdout.strip():
            reading = DiskReading(device_path=path, smart_type=dtype, smart_health="unavailable")
            reading.smart_message = SUDO_HINT if "sudo" in err else (err[:300] or f"smartctl je vratio kod {res.exit_status}.")
            if "sudo" in err:
                ctx.result.errors.append(f"SMART za {path}: {SUDO_HINT}")
            disks.append(reading)
            continue
        try:
            data = json.loads(res.stdout) if json_mode else smart.smartctl_text_to_json(res.stdout)
        except ValueError:
            reading = DiskReading(device_path=path, smart_type=dtype, smart_health="unavailable",
                                  smart_message="Izlaz smartctl-a nije mogao da se pročita.")
            ctx.result.errors.append(f"SMART za {path}: neispravan izlaz smartctl-a.")
            disks.append(reading)
            continue
        if not json_mode:
            data["smartctl"]["exit_status"] = data["smartctl"].get("exit_status") or res.exit_status
        disks.append(smart.parse_smartctl(data, path, dtype))
    return disks


def _merge_lsblk(ctx: Context, disks: list[DiskReading], lsblk_json: str | None) -> None:
    """Dopunjuje tip veze (USB) i dodaje diskove koje smartctl ne vidi, da inventar bude potpun."""
    if not lsblk_json:
        return
    try:
        devices = json.loads(lsblk_json).get("blockdevices", [])
    except ValueError:
        ctx.result.warnings.append("Izlaz lsblk nije mogao da se pročita.")
        return
    known = {storage.disk_key(d.device_path): d for d in disks}
    for dev in devices:
        name = dev.get("name") or ""
        if dev.get("type") != "disk" or re.match(r"^(loop|zd|rbd|dm-|sr|zram|nbd|md)", name):
            continue
        key = storage.disk_key(name)
        reading = known.get(key)
        tran = (dev.get("tran") or "").lower()
        if reading is not None:
            if tran == "usb":
                reading.disk_type = "usb"
                reading.interface_type = "USB"
            if reading.capacity_bytes is None and isinstance(dev.get("size"), int):
                reading.capacity_bytes = dev["size"]
            continue
        path = dev.get("path") or f"/dev/{name}"
        rota = dev.get("rota")
        reading = DiskReading(
            device_path=path,
            model=(dev.get("model") or "").strip() or None,
            vendor=(dev.get("vendor") or "").strip() or None,
            serial_number=(dev.get("serial") or "").strip() or None,
            wwn=dev.get("wwn"),
            firmware=(dev.get("rev") or "").strip() or None,
            capacity_bytes=dev.get("size") if isinstance(dev.get("size"), int) else None,
            disk_type="usb" if tran == "usb" else ("nvme" if tran == "nvme" else ("hdd" if rota is True else ("ssd" if rota is False else "unknown"))),
            interface_type=tran.upper() or None,
            smart_health="unavailable",
            smart_message="smartctl ne vidi ovaj disk (kontroler ili USB adapter ne prosleđuje SMART).",
        )
        reading.stable_identifier = smart.stable_identifier(reading.wwn, None, reading.model, reading.serial_number)
        disks.append(reading)


# --- Platforme ---

_LSBLK = "-J -b -d -o NAME,PATH,TYPE,TRAN,ROTA,SIZE,MODEL,SERIAL,WWN,REV,VENDOR"
_ZPOOL_LIST = "list -Hp -o name,size,alloc,free,frag,cap,health"
_LVS = "--reportformat json --units b --nosuffix -o lv_name,vg_name,lv_attr,lv_size,data_percent,metadata_percent,pool_lv"
_VGS = "--reportformat json --units b --nosuffix -o vg_name,vg_size,vg_free,pv_count,lv_count,vg_attr"


async def _zfs(ctx: Context, linux: bool, labels: dict[str, str] | None = None) -> None:
    zpool = ctx.tool("zpool")
    if not zpool:
        return
    listing = await ctx.call(f"{zpool} {_ZPOOL_LIST}", "ZFS pool-ovi (zpool list)")
    status = await ctx.call(f"{zpool} status -p -P -L" if linux else f"{zpool} status -p", "ZFS status (zpool status)")
    if listing is None or status is None:
        return
    ctx.result.pools.extend(storage.zfs_pools(listing, status, labels))
    ctx.result.pool_sources.add("zfs")


async def _mdstat(ctx: Context) -> None:
    out = await ctx.call("cat /proc/mdstat", "Linux RAID (/proc/mdstat)", ok_codes=(0, 1))
    if out is not None:
        ctx.result.pools.extend(storage.parse_mdstat(out))
        ctx.result.pool_sources.add("mdadm")


async def collect_linux(ctx: Context, platform: str) -> CollectResult:
    disks = await collect_disks(ctx)
    lsblk = ctx.tool("lsblk")
    if lsblk:
        _merge_lsblk(ctx, disks, await ctx.call(f"{lsblk} {_LSBLK}", "Inventar diskova (lsblk)"))
    ctx.result.disks = disks
    await _zfs(ctx, linux=True)
    if platform == "proxmox":
        lvs, vgs = ctx.tool("lvs"), ctx.tool("vgs")
        if lvs and vgs:
            lvs_out = await ctx.call(ctx.privileged(f"{lvs} {_LVS}"), "LVM (lvs)")
            vgs_out = await ctx.call(ctx.privileged(f"{vgs} {_VGS}"), "LVM (vgs)")
            if lvs_out is not None and vgs_out is not None:
                try:
                    ctx.result.pools.extend(storage.lvm_pools(lvs_out, vgs_out))
                    ctx.result.pool_sources.update({"lvm_vg", "lvm_thin"})
                except ValueError:
                    ctx.result.errors.append("LVM: izlaz nije mogao da se pročita.")
        pvesm = ctx.tool("pvesm")
        if pvesm:
            out = await ctx.call(ctx.privileged(f"{pvesm} status"), "Proxmox storage (pvesm status)")
            if out is not None:
                ctx.result.pools.extend(storage.pve_storages(out))
                ctx.result.pool_sources.add("pve_storage")
        await _mdstat(ctx)
    return ctx.result


async def collect_truenas_core(ctx: Context) -> CollectResult:
    disks = await collect_disks(ctx)
    ctx.result.disks = disks
    kern = await ctx.call("sysctl -n kern.disks", "Inventar diskova (kern.disks)")
    if kern:
        known = {storage.disk_key(d.device_path) for d in disks}
        for name in kern.split():
            if storage.disk_key(name) not in known and not name.startswith(("cd", "md")):
                disks.append(DiskReading(
                    device_path=f"/dev/{name}", smart_health="unavailable",
                    smart_message="smartctl ne vidi ovaj disk (kontroler ne prosleđuje SMART).",
                ))
    labels_out = await ctx.call("glabel status -s", "GEOM oznake (glabel)")
    await _zfs(ctx, linux=False, labels=storage.parse_glabel(labels_out or ""))
    return ctx.result


async def collect_synology(ctx: Context) -> CollectResult:
    ctx.result.disks = await collect_disks(ctx, json_mode=await _smartctl_json_ok(ctx))
    await _mdstat(ctx)
    df = await ctx.call("df -kP", "Volumeni (df)")
    if df is not None:
        ctx.result.pools.extend(storage.synology_volumes(df))
        ctx.result.pool_sources.add("synology_volume")
    # md0 (sistem) i md1 (swap) postoje na svakom DSM-u; označavamo ih da ne zbunjuju.
    for pool in ctx.result.pools:
        if pool.technology == "mdadm" and pool.name in ("md0", "md1"):
            pool.details["system"] = True
    return ctx.result


async def collect(platform: str, run: Runner, tools: dict[str, str | None], use_sudo: bool,
                  smartctl_version: str | None = None) -> CollectResult:
    ctx = Context(run, tools, use_sudo)
    if smartctl_version:
        ctx.tools["smartctl_version"] = smartctl_version
    if platform == "truenas_core":
        return await collect_truenas_core(ctx)
    if platform == "synology":
        return await collect_synology(ctx)
    return await collect_linux(ctx, platform)

