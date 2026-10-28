"""Zajednički interni model podataka koji vraćaju svi platformski adapteri."""

from dataclasses import dataclass, field
from typing import Any

# Vrste diska
DISK_TYPES = ("hdd", "ssd", "nvme", "sas", "usb", "unknown")

# SMART stanje u jednom očitavanju. „unavailable” i „standby” nikad ne znače „ispravno”.
SMART_HEALTH = ("passed", "failed", "unknown", "unavailable", "standby")


@dataclass
class SelfTest:
    test_type: str
    status: str
    passed: bool | None
    lifetime_hours: int | None
    remaining_percent: int | None = None


@dataclass
class DiskReading:
    """Jedan disk u jednom ciklusu: identitet + SMART očitavanje."""

    device_path: str
    smart_type: str | None = None  # -d tip za smartctl (sat, nvme, atacam…)
    stable_identifier: str | None = None
    model: str | None = None
    vendor: str | None = None
    serial_number: str | None = None
    wwn: str | None = None
    firmware: str | None = None
    disk_type: str = "unknown"
    interface_type: str | None = None
    capacity_bytes: int | None = None
    rotation_rate: int | None = None
    form_factor: str | None = None

    smart_available: bool = False
    smart_health: str = "unknown"
    smart_message: str | None = None  # razlog kada SMART nije dostupan / poruke alata
    temperature_c: int | None = None
    power_on_hours: int | None = None
    power_cycles: int | None = None
    reallocated_sectors: int | None = None
    pending_sectors: int | None = None
    uncorrectable_sectors: int | None = None
    crc_errors: int | None = None
    reported_uncorrect: int | None = None
    load_cycles: int | None = None
    start_stop_count: int | None = None
    ssd_life_left: int | None = None
    total_lbas_written: int | None = None
    # NVMe
    percentage_used: int | None = None
    available_spare: int | None = None
    available_spare_threshold: int | None = None
    media_errors: int | None = None
    critical_warning: int | None = None
    unsafe_shutdowns: int | None = None
    data_units_read: int | None = None
    data_units_written: int | None = None
    host_read_commands: int | None = None
    host_write_commands: int | None = None
    controller_busy_time: int | None = None
    error_log_entries: int | None = None
    warning_temp_time: int | None = None
    critical_temp_time: int | None = None

    error_log_count: int | None = None
    self_test_running: bool = False
    self_test_status: str | None = None
    attributes: list[dict[str, Any]] = field(default_factory=list)
    self_tests: list[SelfTest] = field(default_factory=list)
    raw: dict[str, Any] | None = None


@dataclass
class PoolMember:
    name: str
    state: str | None = None
    read_errors: int | None = None
    write_errors: int | None = None
    checksum_errors: int | None = None
    disk_path: str | None = None  # razrešen fizički disk (/dev/sda), ako je poznat
    kind: str = "disk"  # disk / vdev (raidz2-0, mirror-0…) / group (logs, cache, spares)
    depth: int = 0
    note: str | None = None


@dataclass
class PoolReading:
    name: str
    technology: str  # zfs / lvm_thin / lvm_vg / mdadm / pve_storage / synology_volume
    status: str  # ONLINE, DEGRADED…, active, clean…
    healthy: bool | None  # None = ne može se proceniti
    capacity_bytes: int | None = None
    used_bytes: int | None = None
    free_bytes: int | None = None
    read_errors: int | None = None
    write_errors: int | None = None
    checksum_errors: int | None = None
    scan_type: str | None = None  # scrub / resilver
    scan_state: str | None = None  # in_progress / finished / canceled / none
    scan_progress: float | None = None  # 0-100
    scan_errors: int | None = None
    scan_finished_at: str | None = None  # kako ga ispisuje alat (lokalno vreme uređaja)
    scan_text: str | None = None
    redundancy: str | None = None  # npr. raidz2, mirror, stripe, raid1
    message: str | None = None  # status/action poruka alata
    data_errors: str | None = None
    members: list[PoolMember] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectResult:
    disks: list[DiskReading] = field(default_factory=list)
    pools: list[PoolReading] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # greške pojedinih koraka (ciklus je delimično uspešan)
    warnings: list[str] = field(default_factory=list)
    # Da li je spisak diskova potpun (pretraga uspela); samo tada se diskovi kojih nema označavaju kao nestali.
    disks_complete: bool = False
    # Tehnologije skladišta koje su uspešno očitane (i kada nema nijednog pool-a).
    pool_sources: set[str] = field(default_factory=set)
    # Promene inventara otkrivene pri upisu (spec. §16.2): {rule, disk_id|pool_id, title, message}
    changes: list[dict[str, Any]] = field(default_factory=list)
