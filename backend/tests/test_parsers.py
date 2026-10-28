"""Testovi parsera na stvarnim izlazima sa Proxmox VE 9 i TrueNAS CORE 13 (tests/fixtures)."""

import asyncio
import json
from pathlib import Path

from app.adapters import platforms, smart, storage
from app.ssh.client import CommandResult

FX = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FX / name).read_text(encoding="utf-8"))


def text(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


def test_sata_hdd():
    r = smart.parse_smartctl(load("pve_smart_sata_hdd.json"), "/dev/sda", "sat")
    assert r.disk_type == "hdd" and r.rotation_rate == 5400
    assert r.smart_health == "passed" and r.smart_available
    assert r.model == "ST1000LM035-1RK172"
    assert r.stable_identifier.startswith("wwn-0x5000c5")
    assert r.power_on_hours == 10495  # iz power_on_time, ne iz spakovanog raw-a
    assert r.temperature_c == 42
    assert r.reallocated_sectors == 0 and r.pending_sectors == 0 and r.crc_errors == 2
    assert r.load_cycles == 29591
    assert len(r.attributes) == 24
    assert r.self_tests and r.self_tests[0].status == "Aborted by host"


def test_sata_ssd():
    r = smart.parse_smartctl(load("pve_smart_sata_ssd.json"), "/dev/sda", "sat")
    assert r.disk_type == "ssd"
    assert r.temperature_c == 29 and r.power_on_hours == 4973
    assert r.self_tests == []


def test_nvme():
    r = smart.parse_smartctl(load("pve_smart_nvme.json"), "/dev/nvme0", "nvme")
    assert r.disk_type == "nvme" and r.smart_health == "passed"
    assert r.percentage_used == 30 and r.available_spare == 100 and r.available_spare_threshold == 10
    assert r.unsafe_shutdowns == 6 and r.media_errors == 0 and r.critical_warning == 0
    assert r.data_units_written == 22849833
    assert r.stable_identifier  # eui64 ili serijski broj
    assert r.self_test_running is False


def test_core_disks():
    r = smart.parse_smartctl(load("core_smart_ada0.json"), "/dev/ada0", "atacam")
    assert r.disk_type == "hdd" and r.vendor == "Seagate IronWolf"
    assert r.power_on_hours == 34565
    assert r.smart_health == "passed"
    n = smart.parse_smartctl(load("core_smart_nvme.json"), "/dev/nvme0", "nvme")
    assert n.disk_type == "nvme" and n.unsafe_shutdowns == 57


def test_failed_and_standby():
    data = load("pve_smart_sata_hdd.json")
    data["smart_status"] = {"passed": False}
    assert smart.parse_smartctl(data, "/dev/sda").smart_health == "failed"
    standby = {"smartctl": {"exit_status": 2, "messages": [{"string": "Device is in STANDBY mode, exit(2)", "severity": "information"}]},
               "device": {"name": "/dev/sda", "type": "sat", "protocol": "ATA"}}
    r = smart.parse_smartctl(standby, "/dev/sda")
    assert r.smart_health == "standby" and not r.smart_available
    nosmart = {"smartctl": {"exit_status": 4}, "device": {"protocol": "ATA"}, "smart_support": {"available": False}}
    assert smart.parse_smartctl(nosmart, "/dev/sdb").smart_health == "unavailable"


def test_scan_skips_enclosure():
    found = platforms.parse_scan(text("core_scan.json"))
    paths = [p for p, _ in found]
    assert "/dev/ses0" not in paths and "/dev/ada0" in paths and "/dev/nvme0" in paths
    assert len(found) == 10
    assert platforms.parse_scan('{"devices":[{"name":"/dev/sda; rm -rf /","type":"sat"}]}') == []
    assert platforms.parse_scan('{"devices":[{"name":"/dev/sdb","type":"sat -t long"}]}') == [("/dev/sdb", "auto")]


def test_zfs_core():
    labels = storage.parse_glabel(text("core_glabel.txt"))
    pools = {p.name: p for p in storage.zfs_pools(text("core_zpool_list.txt"), text("core_zpool_status.txt"), labels)}
    assert set(pools) == {"DataPool", "MediaPool", "boot-pool"}
    data = pools["DataPool"]
    assert data.healthy and data.status == "ONLINE"
    assert data.redundancy == "raidz2"
    assert data.scan_type == "scrub" and data.scan_state == "finished" and data.scan_errors == 0
    assert data.scan_finished_at == "Sun Oct 4 00:20:38 2026"
    disks = [m for m in data.members if m.kind == "disk"]
    assert len(disks) == 7 and all(m.disk_path and m.disk_path.startswith("ada") for m in disks)
    assert data.capacity_bytes == 13984413515776
    assert pools["MediaPool"].redundancy == "stripe"
    boot = pools["boot-pool"]
    assert boot.redundancy == "single" and boot.members[0].disk_path == "nvme0"


DEGRADED = """  pool: tank
 state: DEGRADED
status: One or more devices could not be used because the label is missing or
\tinvalid.  Sufficient replicas exist for the pool to continue
\tfunctioning in a degraded state.
action: Replace the device using 'zpool replace'.
  scan: resilver in progress since Wed Oct 28 10:00:00 2026
\t1.23T scanned at 500M/s, 800G issued at 300M/s, 5.00T total
\t200G resilvered, 16.00% done, 03:50:00 to go
config:

\tNAME                        STATE     READ WRITE CKSUM
\ttank                        DEGRADED     0     0     0
\t  mirror-0                  DEGRADED     0     0     0
\t    /dev/sda1               ONLINE       0     0     3
\t    replacing-1             DEGRADED     0     0     0
\t      /dev/sdb1             UNAVAIL      0     0     0  was /dev/sdb1
\t      /dev/sdc1             ONLINE       0     0     0  (resilvering)
\tlogs
\t  /dev/nvme0n1p1            ONLINE       0     0     0
\tspares
\t  /dev/sdd1                 AVAIL

errors: No known data errors
"""


def test_zfs_degraded_resilver():
    pool = storage.parse_zpool_status(DEGRADED)["tank"]
    assert pool.healthy is False and pool.status == "DEGRADED"
    assert pool.scan_type == "resilver" and pool.scan_state == "in_progress" and pool.scan_progress == 16.0
    assert pool.redundancy == "mirror"
    by_name = {m.name: m for m in pool.members}
    assert by_name["/dev/sda1"].checksum_errors == 3 and by_name["/dev/sda1"].disk_path == "sda"
    assert by_name["/dev/sdb1"].state == "UNAVAIL" and by_name["/dev/sdb1"].note == "was /dev/sdb1"
    assert by_name["/dev/sdc1"].depth == 3
    assert by_name["logs"].kind == "group" and by_name["/dev/nvme0n1p1"].disk_path == "nvme0"
    assert by_name["/dev/sdd1"].state == "AVAIL"


def test_lvm_and_pvesm():
    pools = storage.lvm_pools(text("pve_lvs.json"), text("pve_vgs.json"))
    thin = next(p for p in pools if p.technology == "lvm_thin")
    assert thin.name == "pve/data" and thin.healthy and thin.details["data_percent"] == 11.78
    assert thin.details["thin_volumes"] >= 5
    vg = next(p for p in pools if p.technology == "lvm_vg")
    assert vg.name == "pve" and vg.capacity_bytes and vg.free_bytes
    st = {p.name: p for p in storage.pve_storages(text("pve_pvesm.txt"))}
    assert st["local-lvm"].details["type"] == "lvmthin" and st["local-lvm"].healthy
    assert st["pbs-backup"].capacity_bytes == 9488256000 * 1024


MDSTAT = """Personalities : [raid1] [raid6] [raid5] [raid4]
md2 : active raid5 sata3p3[2] sata2p3[1](F) sata1p3[0]
      7804393472 blocks super 1.2 level 5, 64k chunk, algorithm 2 [3/2] [U_U]
      [=>...................]  recovery =  8.1% (316000000/3902196736) finish=300.0min speed=200000K/sec

md1 : active raid1 sata1p2[0] sata2p2[1] sata3p2[2]
      2097088 blocks [16/3] [UUU_____________]

unused devices: <none>
"""


def test_mdstat():
    pools = {p.name: p for p in storage.parse_mdstat(MDSTAT)}
    md2 = pools["md2"]
    assert md2.healthy is False and md2.status == "degraded" and md2.redundancy == "raid5"
    assert md2.scan_type == "recovery" and md2.scan_progress == 8.1
    assert [m.state for m in md2.members] == ["ONLINE", "FAULTED", "ONLINE"]
    assert md2.members[0].disk_path == "sata3"


SMART_TEXT = """smartctl 6.5 (build date Sep 26 2022) [x86_64-linux-4.4.302+] (local build)
=== START OF INFORMATION SECTION ===
Model Family:     Western Digital Red
Device Model:     WDC WD40EFRX-68N32N0
Serial Number:    WD-WCC7K0000000
LU WWN Device Id: 5 0014ee 2b0000000
Firmware Version: 82.00A82
User Capacity:    4,000,787,030,016 bytes [4.00 TB]
Rotation Rate:    5400 rpm
SMART support is: Available - device has SMART capability.
SMART support is: Enabled

=== START OF READ SMART DATA SECTION ===
SMART overall-health self-assessment test result: PASSED

ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  5 Reallocated_Sector_Ct   0x0033   200   200   140    Pre-fail  Always       -       8
  9 Power_On_Hours          0x0032   063   063   000    Old_age   Always       -       27345
194 Temperature_Celsius     0x0022   117   105   000    Old_age   Always       -       35
197 Current_Pending_Sector  0x0032   200   200   000    Old_age   Always       -       1
"""


def test_smart_text_fallback():
    r = smart.parse_smartctl(smart.smartctl_text_to_json(SMART_TEXT), "/dev/sata1", "sat")
    assert r.model == "WDC WD40EFRX-68N32N0" and r.vendor == "Western Digital Red"
    assert r.smart_health == "passed" and r.disk_type == "hdd"
    assert r.reallocated_sectors == 8 and r.pending_sectors == 1 and r.temperature_c == 35
    assert r.power_on_hours == 27345 and r.capacity_bytes == 4000787030016
    assert r.stable_identifier == "wwn-0x50014ee2b0000000"


def test_disk_key():
    assert storage.disk_key("/dev/sda1") == "sda"
    assert storage.disk_key("/dev/nvme0n1p2") == "nvme0"
    assert storage.disk_key("nvd0p2") == "nvme0"
    assert storage.disk_key("ada10p2") == "ada10"
    assert storage.disk_key("sata2p3") == "sata2"


def test_collect_proxmox_end_to_end():
    """Ceo adapter sa simuliranim uređajem: odgovori su stvarni izlazi sa Proxmox hosta."""
    outputs = {
        "smartctl -j --scan-open": text("pve_scan.json"),
        "-d sat /dev/sda": text("pve_smart_sata_hdd.json"),
        "-d nvme /dev/nvme0": text("pve_smart_nvme.json"),
        "lsblk": text("pve_lsblk.json"),
        "/usr/sbin/lvs": text("pve_lvs.json"),
        "/usr/sbin/vgs": text("pve_vgs.json"),
        "pvesm status": text("pve_pvesm.txt"),
        "/proc/mdstat": "Personalities : \nunused devices: <none>\n",
    }
    commands: list[str] = []

    async def run(cmd: str) -> CommandResult:
        commands.append(cmd)
        for key, out in outputs.items():
            if key in cmd:
                return CommandResult(0, out, "", False)
        return CommandResult(1, "", "no pools available", False)

    tools = {"smartctl": "/usr/sbin/smartctl", "lsblk": "/usr/bin/lsblk", "lvs": "/usr/sbin/lvs",
             "vgs": "/usr/sbin/vgs", "pvesm": "/usr/sbin/pvesm", "zpool": None}
    result = asyncio.run(platforms.collect("proxmox", run, tools, use_sudo=True))
    assert len(result.disks) == 2
    assert {d.disk_type for d in result.disks} == {"hdd", "nvme"}
    assert {p.technology for p in result.pools} == {"lvm_vg", "lvm_thin", "pve_storage"}
    assert result.errors == []
    assert "sudo -n /usr/sbin/smartctl -j -a -n standby -d sat /dev/sda" in commands
    assert all(not c.startswith("sudo") for c in commands if "lsblk" in c)
