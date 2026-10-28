"""Profili privilegija po platformi: tačne komande koje namenski nalog sme da izvrši preko sudo-a.

Spisak se pravi iz istih šablona koje koristi adapter (platforms.py), tako da se profil i stvarne komande
ne mogu razići. Džokeri se ne koriste u argumentima (u sudoers-u `*` hvata i razmake, pa bi dozvolio npr.
`-t long`), već samo klase znakova za ime diska (`/dev/sd[a-z]`), koje hvataju tačno jedan znak.
"""

from .platforms import _LVS, _VGS

# Putanje alata po platformi (proverene na stvarnim sistemima: Proxmox VE 9, TrueNAS CORE 13).
LINUX_SMARTCTL = "/usr/sbin/smartctl"
CORE_SMARTCTL = "/usr/local/sbin/smartctl"

_LINUX_DISKS = {
    ("sat", "scsi", "ata", "auto"): ["/dev/sd[a-z]", "/dev/sd[a-z][a-z]"],
    ("nvme",): ["/dev/nvme[0-9]", "/dev/nvme[0-9][0-9]"],
}
_CORE_DISKS = {
    ("atacam", "ata", "sat", "auto"): ["/dev/ada[0-9]", "/dev/ada[0-9][0-9]"],
    ("scsi", "sat", "auto"): ["/dev/da[0-9]", "/dev/da[0-9][0-9]"],
    ("nvme",): ["/dev/nvme[0-9]", "/dev/nvme[0-9][0-9]"],
}
_SYNOLOGY_DISKS = {
    ("sat", "ata", "auto"): ["/dev/sd[a-z]", "/dev/sata[0-9]", "/dev/sata[0-9][0-9]"],
    ("nvme",): ["/dev/nvme[0-9]"],
}


def _smart_commands(smartctl: str, matrix: dict[tuple[str, ...], list[str]], json_mode: bool = True) -> list[str]:
    flag = "-j " if json_mode else ""
    commands = [f"{smartctl} {flag}--scan-open"]
    for types, paths in matrix.items():
        for dtype in types:
            for path in paths:
                commands.append(f"{smartctl} {flag}-a -n standby -d {dtype} {path}")
    return commands


def sudo_commands(platform: str) -> list[str]:
    """Komande koje zahtevaju root. Ostale (zpool, lsblk, glabel, /proc/mdstat) rade bez privilegija."""
    if platform == "proxmox":
        return _smart_commands(LINUX_SMARTCTL, _LINUX_DISKS) + [
            f"/usr/sbin/lvs {_LVS}",
            f"/usr/sbin/vgs {_VGS}",
            "/usr/sbin/pvesm status",
        ]
    if platform == "truenas_scale":
        return _smart_commands(LINUX_SMARTCTL, _LINUX_DISKS)
    if platform == "truenas_core":
        return _smart_commands(CORE_SMARTCTL, _CORE_DISKS)
    if platform == "synology":
        # DSM ima smartctl 6.x bez JSON-a; putanja može da se razlikuje po modelu.
        return _smart_commands("/usr/bin/smartctl", _SYNOLOGY_DISKS, json_mode=False)
    return []


# Komande koje rade bez privilegija (informativno, za prikaz u UI-ju).
UNPRIVILEGED: dict[str, list[str]] = {
    "proxmox": ["lsblk -J -b -d -o …", "zpool list -Hp …", "zpool status -p -P -L", "cat /proc/mdstat"],
    "truenas_scale": ["lsblk -J -b -d -o …", "zpool list -Hp …", "zpool status -p -P -L"],
    "truenas_core": ["zpool list -Hp …", "zpool status -p", "glabel status -s", "sysctl -n kern.disks"],
    "synology": ["cat /proc/mdstat", "df -kP"],
}

NOTES: dict[str, list[str]] = {
    "proxmox": [
        "Na Proxmox VE sudo nije instaliran podrazumevano: apt install sudo.",
        "Nalog: useradd -m -s /bin/bash diskmonitor && passwd -l diskmonitor (prijava samo ključem).",
        "Profil sačuvati kao /etc/sudoers.d/smartdisk (vlasnik root, prava 0440) i proveriti sa visudo -c.",
    ],
    "truenas_scale": [
        "Nalog i sudo komande podešavaju se kroz web interfejs (Credentials → Users) ili middleware, "
        "ne ručnom izmenom fajlova – TrueNAS ih prepisuje.",
        "U polje „Allowed sudo commands with no password” uneti komande iz spiska (svaku posebno).",
    ],
    "truenas_core": [
        "Nalog i sudo komande podešavaju se kroz middleware (midclt user.create/user.update: sudo=true, "
        "sudo_nopasswd=true, sudo_commands=[…]) ili web interfejs; ručne izmene sudoers-a TrueNAS prepisuje.",
        "Home direktorijum mora biti na pool-u (npr. /mnt/DataPool/diskmonitor) da bi SSH ključ mogao da se sačuva.",
        "Prazan spisak komanda u TrueNAS-u znači „sve komande” – spisak nikad ne ostavljati prazan.",
    ],
    "synology": [
        "Netestirano na stvarnom uređaju. DSM 7 koristi smartctl 6.x (tekstualni izlaz) – putanju proveriti sa "
        "command -v smartctl.",
        "Profil sačuvati kao /etc/sudoers.d/smartdisk; DSM nadogradnja može da ga ukloni, pa ga posle nadogradnje proveriti.",
    ],
}


def _escape(command: str) -> str:
    # U sudoers-u zarez razdvaja komande, a dvotačka i znak jednakosti imaju posebno značenje.
    return command.replace("\\", "\\\\").replace(",", "\\,").replace(":", "\\:").replace("=", "\\=")


def sudoers_file(platform: str, username: str = "diskmonitor") -> str:
    commands = sudo_commands(platform)
    lines = [
        f"# SmartDisk – read-only profil za nalog {username} ({platform}).",
        "# Samo navedene komande, bez lozinke, bez opšteg sudo pristupa. Proveriti sa: visudo -cf <fajl>",
        f"Defaults:{username} !requiretty",
        "Cmnd_Alias SMARTDISK_READ = \\",
    ]
    for i, command in enumerate(commands):
        lines.append(f"    {_escape(command)}" + (", \\" if i < len(commands) - 1 else ""))
    lines.append(f"{username} ALL=(root) NOPASSWD: SMARTDISK_READ")
    return "\n".join(lines) + "\n"
