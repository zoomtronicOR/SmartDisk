"""Detekcija operativnog sistema i dostupnih alata na uređaju (samo read-only komande)."""

import re
import shlex
from dataclasses import dataclass, field

# Alati koji se traže; opis se prikazuje u UI-ju.
TOOLS: dict[str, str] = {
    "smartctl": "SMART podaci (smartmontools)",
    "lsblk": "Inventar blok uređaja",
    "nvme": "NVMe alati (nvme-cli)",
    "zpool": "ZFS pool status",
    "zfs": "ZFS dataset-i",
    "mdadm": "Linux softverski RAID",
    "lvs": "LVM / LVM-thin",
    "vgs": "LVM volume grupe",
    "pvesm": "Proxmox storage",
    "midclt": "TrueNAS middleware klijent",
    "synodisk": "Synology alat za diskove",
}

# Koji alati se očekuju na kojoj platformi (za upozorenja o nedostajućim funkcijama).
EXPECTED: dict[str, list[str]] = {
    "truenas_scale": ["smartctl", "lsblk", "zpool", "zfs"],
    "truenas_core": ["smartctl", "zpool", "zfs"],
    "proxmox": ["smartctl", "lsblk", "lvs", "vgs", "pvesm"],
    "synology": ["smartctl", "mdadm"],
}

_TOOL_LIST = " ".join(TOOLS)

# Izvršava se kroz `sh -c` jer korisnički shell može biti csh/zsh (npr. TrueNAS CORE).
_SCRIPT = (
    'PATH="$PATH:/usr/sbin:/sbin:/usr/local/sbin:/usr/local/bin:/usr/syno/bin:/usr/syno/sbin"; export PATH; '
    'echo "@@uname"; uname -srm 2>/dev/null; '
    'echo "@@os_release"; cat /etc/os-release 2>/dev/null; '
    'echo "@@synology"; cat /etc.defaults/VERSION 2>/dev/null; '
    'echo "@@freebsd"; freebsd-version 2>/dev/null; '
    'echo "@@pve"; pveversion 2>/dev/null; '
    'echo "@@truenas"; cat /etc/version 2>/dev/null; '
    f'echo "@@tools"; for t in {_TOOL_LIST}; do echo "$t=$(command -v "$t" 2>/dev/null)"; done; '
    'echo "@@smartctl"; smartctl --version 2>/dev/null | head -n 1; '
    'echo "@@epoch"; date +%s; '
    "true"
)

PROBE_COMMAND = "sh -c " + shlex.quote(_SCRIPT)


@dataclass
class ProbeResult:
    os_info: str
    detected_platform: str | None
    tools: dict[str, str | None]  # alat -> putanja ili None
    smartctl_version: str | None
    warnings: list[str] = field(default_factory=list)
    device_epoch: int | None = None  # sat uređaja (Unix vreme) u trenutku izvršavanja


def _sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in output.splitlines():
        if line.startswith("@@"):
            current = line[2:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _kv(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"')
    return result


def parse_probe(output: str, configured_platform: str) -> ProbeResult:
    s = _sections(output)
    os_release = _kv(s.get("os_release", ""))
    synology = _kv(s.get("synology", ""))
    freebsd = s.get("freebsd", "")
    pve = s.get("pve", "")
    truenas = s.get("truenas", "").splitlines()[0] if s.get("truenas") else ""

    detected: str | None = None
    if synology.get("productversion"):
        detected = "synology"
        build = synology.get("buildnumber")
        os_info = f"Synology DSM {synology['productversion']}" + (f"-{build}" if build else "")
    elif pve:
        detected = "proxmox"
        match = re.search(r"pve-manager/([\w.\-]+)", pve)
        os_info = f"Proxmox VE {match.group(1) if match else pve.splitlines()[0]}"
    elif truenas and freebsd:
        detected = "truenas_core"
        os_info = f"TrueNAS CORE {truenas} (FreeBSD {freebsd})"
    elif truenas:
        detected = "truenas_scale"
        os_info = f"TrueNAS SCALE {truenas}"
    elif os_release.get("PRETTY_NAME"):
        os_info = os_release["PRETTY_NAME"]
    elif freebsd:
        os_info = f"FreeBSD {freebsd}"
    else:
        os_info = s.get("uname", "") or "Nepoznat sistem"

    tools_raw = _kv(s.get("tools", ""))
    tools = {name: (tools_raw.get(name) or None) for name in TOOLS}
    smartctl_version = s.get("smartctl") or None

    warnings: list[str] = []
    if detected and detected != configured_platform:
        warnings.append(
            f"Na uređaju je prepoznat sistem „{os_info}”, a podešena platforma je drugačija. Proverite tip platforme."
        )
    for tool in EXPECTED.get(configured_platform, []):
        if not tools.get(tool):
            warnings.append(f"Alat „{tool}” nije pronađen – nedostupno: {TOOLS[tool]}.")

    epoch = s.get("epoch", "").strip()
    return ProbeResult(os_info[:255], detected, tools, smartctl_version, warnings,
                       int(epoch) if epoch.isdigit() else None)
