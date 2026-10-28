"""Parsiranje izlaza `smartctl -j -a` (smartmontools 7+) i tekstualnog izlaza starijih verzija."""

import re
from typing import Any

from .model import DiskReading, SelfTest

# Vrednosti za ove atribute uzimaju se iz normalizovane vrednosti (procenat preostalog veka SSD-a).
_LIFE_LEFT_NAMES = {
    "SSD_Life_Left",
    "Percent_Lifetime_Remain",
    "Media_Wearout_Indicator",
    "Wear_Leveling_Count",
    "Remaining_Lifetime_Perc",
    "Percent_Life_Remaining",
}

# smartctl exit status (bitovi), videti `man smartctl`.
EXIT_PARSE_ERROR = 1
EXIT_OPEN_FAILED = 2
EXIT_SMART_CMD_FAILED = 4
EXIT_DISK_FAILING = 8
EXIT_PREFAIL_BELOW = 16
EXIT_ATTR_BELOW_PAST = 32
EXIT_ERROR_LOG = 64
EXIT_SELFTEST_ERRORS = 128


def _raw_int(attr: dict[str, Any]) -> int | None:
    """Raw vrednost brojača. Kada je raw „spakovan” (npr. „10495 (205 22 0)”), uzima se prvi broj."""
    raw = attr.get("raw") or {}
    text = str(raw.get("string", "")).strip()
    match = re.match(r"^(\d+)(?:\s|$|h)", text)
    if match:
        return int(match.group(1))
    value = raw.get("value")
    return int(value) if isinstance(value, int) else None


def _wwn(data: dict[str, Any]) -> str | None:
    wwn = data.get("wwn")
    if isinstance(wwn, dict) and {"naa", "oui", "id"} <= wwn.keys():
        return f"0x{wwn['naa']:x}{wwn['oui']:06x}{wwn['id']:09x}"
    return None


def _eui(data: dict[str, Any]) -> str | None:
    for ns in data.get("nvme_namespaces") or []:
        eui = ns.get("eui64")
        if isinstance(eui, dict) and "oui" in eui and "ext_id" in eui:
            return f"eui.{eui['oui']:06x}{eui['ext_id']:010x}"
        nguid = ns.get("nguid")
        if isinstance(nguid, str) and nguid.strip("0- "):
            return f"nguid.{nguid.replace('-', '')}"
    return None


def stable_identifier(wwn: str | None, eui: str | None, model: str | None, serial: str | None) -> str | None:
    if wwn:
        return f"wwn-{wwn}"
    if eui:
        return eui
    if serial:
        return f"serial-{(model or '').strip()}-{serial.strip()}"
    return None


def _messages(data: dict[str, Any]) -> list[str]:
    return [str(m.get("string", "")) for m in (data.get("smartctl") or {}).get("messages") or []]


def parse_smartctl(data: dict[str, Any], device_path: str, smart_type: str | None = None) -> DiskReading:
    """Pretvara JSON izlaz `smartctl -j -a` u DiskReading. Nikad ne zaključuje „ispravno” bez SMART statusa."""
    device = data.get("device") or {}
    protocol = str(device.get("protocol") or "")
    dev_type = str(device.get("type") or smart_type or "")
    exit_status = int((data.get("smartctl") or {}).get("exit_status") or 0)
    messages = _messages(data)

    r = DiskReading(device_path=device_path, smart_type=smart_type or dev_type or None, raw=data)
    r.model = data.get("model_name") or data.get("scsi_model_name") or data.get("product")
    r.vendor = data.get("model_family") or data.get("scsi_vendor") or data.get("vendor")
    r.serial_number = data.get("serial_number")
    r.firmware = data.get("firmware_version") or data.get("scsi_revision") or data.get("revision")
    r.capacity_bytes = (data.get("user_capacity") or {}).get("bytes") or data.get("nvme_total_capacity")
    rotation = data.get("rotation_rate")
    r.rotation_rate = rotation if isinstance(rotation, int) else None
    r.form_factor = (data.get("form_factor") or {}).get("name")
    r.wwn = _wwn(data)
    r.stable_identifier = stable_identifier(r.wwn, _eui(data), r.model, r.serial_number)

    if protocol == "NVMe" or dev_type == "nvme":
        r.disk_type = "nvme"
        r.interface_type = "NVMe"
    elif protocol == "SCSI":
        r.disk_type = "sas" if r.rotation_rate != 0 else "ssd"
        r.interface_type = "SAS/SCSI"
    elif protocol == "ATA":
        r.disk_type = "ssd" if r.rotation_rate == 0 else ("hdd" if r.rotation_rate else "unknown")
        speed = ((data.get("interface_speed") or {}).get("current") or {}).get("string")
        r.interface_type = f"SATA {speed}" if speed else "SATA"
    if "usb" in dev_type.lower():
        r.disk_type = "usb"

    # Disk u standby režimu (smartctl -n standby): ne budimo ga i ne tumačimo kao grešku diska.
    if exit_status & EXIT_OPEN_FAILED and any("STANDBY" in m or "SLEEP" in m for m in messages):
        r.smart_health = "standby"
        r.smart_message = "Disk je u standby režimu – SMART nije očitan da se disk ne bi budio."
        return r
    if exit_status & EXIT_OPEN_FAILED:
        r.smart_health = "unavailable"
        r.smart_message = "; ".join(messages) or "smartctl nije mogao da otvori uređaj."
        return r

    support = data.get("smart_support")
    status = data.get("smart_status")
    if isinstance(support, dict) and support.get("available") is False:
        r.smart_health = "unavailable"
        r.smart_message = "Uređaj ne podržava SMART (ili ga kontroler ne prosleđuje)."
    elif isinstance(support, dict) and support.get("enabled") is False:
        r.smart_health = "unavailable"
        r.smart_message = "SMART je isključen na disku."
    elif isinstance(status, dict) and "passed" in status:
        r.smart_available = True
        r.smart_health = "passed" if status["passed"] else "failed"
    else:
        r.smart_available = bool(data.get("ata_smart_attributes") or data.get("nvme_smart_health_information_log"))
        r.smart_health = "unknown"
        r.smart_message = "; ".join(messages) or "smartctl nije vratio SMART overall-health status."
    if exit_status & EXIT_DISK_FAILING:
        r.smart_health = "failed"

    temp = (data.get("temperature") or {}).get("current")
    r.temperature_c = temp if isinstance(temp, int) else None
    r.power_on_hours = (data.get("power_on_time") or {}).get("hours")
    r.power_cycles = data.get("power_cycle_count")

    # SATA/SAS atributi
    for attr in (data.get("ata_smart_attributes") or {}).get("table") or []:
        aid = attr.get("id")
        raw = _raw_int(attr)
        when_failed = attr.get("when_failed") or ""
        r.attributes.append({
            "id": aid,
            "name": attr.get("name"),
            "value": attr.get("value"),
            "worst": attr.get("worst"),
            "thresh": attr.get("thresh"),
            "raw": raw,
            "raw_string": (attr.get("raw") or {}).get("string"),
            "prefail": bool((attr.get("flags") or {}).get("prefailure")),
            "when_failed": when_failed or None,
        })
        if aid == 5:
            r.reallocated_sectors = raw
        elif aid == 197:
            r.pending_sectors = raw
        elif aid == 198:
            r.uncorrectable_sectors = raw
        elif aid == 199:
            r.crc_errors = raw
        elif aid == 187:
            r.reported_uncorrect = raw
        elif aid == 193:
            r.load_cycles = raw
        elif aid == 4:
            r.start_stop_count = raw
        elif aid == 241:
            r.total_lbas_written = raw
        elif aid == 9 and r.power_on_hours is None:
            r.power_on_hours = raw
        elif aid == 12 and r.power_cycles is None:
            r.power_cycles = raw
        elif aid in (194, 190) and r.temperature_c is None and raw is not None and raw < 150:
            r.temperature_c = raw
        if attr.get("name") in _LIFE_LEFT_NAMES and isinstance(attr.get("value"), int):
            r.ssd_life_left = attr["value"]

    # SCSI/SAS brojači grešaka
    defects = data.get("scsi_grown_defect_list")
    if isinstance(defects, int):
        r.reallocated_sectors = defects

    # NVMe
    nvme = data.get("nvme_smart_health_information_log")
    if isinstance(nvme, dict):
        r.critical_warning = nvme.get("critical_warning")
        r.available_spare = nvme.get("available_spare")
        r.available_spare_threshold = nvme.get("available_spare_threshold")
        r.percentage_used = nvme.get("percentage_used")
        r.data_units_read = nvme.get("data_units_read")
        r.data_units_written = nvme.get("data_units_written")
        r.host_read_commands = nvme.get("host_reads")
        r.host_write_commands = nvme.get("host_writes")
        r.controller_busy_time = nvme.get("controller_busy_time")
        r.unsafe_shutdowns = nvme.get("unsafe_shutdowns")
        r.media_errors = nvme.get("media_errors")
        r.error_log_entries = nvme.get("num_err_log_entries")
        r.warning_temp_time = nvme.get("warning_temp_time")
        r.critical_temp_time = nvme.get("critical_comp_time")
        if r.temperature_c is None and isinstance(nvme.get("temperature"), int):
            r.temperature_c = nvme["temperature"]
        if r.power_on_hours is None:
            r.power_on_hours = nvme.get("power_on_hours")
        if r.power_cycles is None:
            r.power_cycles = nvme.get("power_cycles")
        if r.critical_warning and r.smart_health == "passed":
            r.smart_health = "failed"

    # Log grešaka
    err_log = data.get("ata_smart_error_log")
    if isinstance(err_log, dict):
        r.error_log_count = (err_log.get("summary") or err_log.get("extended") or {}).get("count")
    elif r.error_log_entries is not None:
        r.error_log_count = r.error_log_entries

    _parse_self_tests(data, r)

    if exit_status & EXIT_SMART_CMD_FAILED and not r.smart_message:
        r.smart_message = "Neke SMART komande nisu uspele: " + ("; ".join(messages) or "bez detalja")
    return r


def _parse_self_tests(data: dict[str, Any], r: DiskReading) -> None:
    ata = (data.get("ata_smart_data") or {}).get("self_test") or {}
    status = ata.get("status") or {}
    if isinstance(status.get("value"), int):
        r.self_test_running = (status["value"] >> 4) == 0xF
        r.self_test_status = status.get("string")
    for entry in ((data.get("ata_smart_self_test_log") or {}).get("standard") or {}).get("table") or []:
        st = entry.get("status") or {}
        r.self_tests.append(SelfTest(
            test_type=(entry.get("type") or {}).get("string") or "?",
            status=st.get("string") or "?",
            passed=st.get("passed"),
            lifetime_hours=entry.get("lifetime_hours"),
            remaining_percent=st.get("remaining_percent"),
        ))

    nvme = data.get("nvme_self_test_log")
    if isinstance(nvme, dict):
        current = nvme.get("current_self_test_operation") or {}
        if current.get("value"):
            r.self_test_running = True
            r.self_test_status = current.get("string")
        elif r.self_test_status is None and current:
            r.self_test_status = current.get("string")
        for entry in nvme.get("table") or []:
            result = entry.get("self_test_result") or {}
            r.self_tests.append(SelfTest(
                test_type=(entry.get("self_test_code") or {}).get("string") or "?",
                status=result.get("string") or "?",
                passed=result.get("value") == 0 if isinstance(result.get("value"), int) else None,
                lifetime_hours=entry.get("power_on_hours"),
            ))
    # SCSI
    for key, entry in (data.get("scsi_self_test_log") or {}).items() if isinstance(data.get("scsi_self_test_log"), dict) else []:
        if not key.startswith("scsi_self_test_") or not isinstance(entry, dict):
            continue
        result = entry.get("result") or {}
        r.self_tests.append(SelfTest(
            test_type=(entry.get("code") or {}).get("string") or "?",
            status=result.get("string") or "?",
            passed=result.get("value") == 0 if isinstance(result.get("value"), int) else None,
            lifetime_hours=(entry.get("power_on_time") or {}).get("hours"),
        ))


# --- Tekstualni izlaz (smartctl 6.x, npr. na starijim Synology DSM) ---

_INFO_RE = {
    "model_family": r"^Model Family:\s+(.+)$",
    "model_name": r"^(?:Device Model|Model Number|Product):\s+(.+)$",
    "serial_number": r"^Serial Number:\s+(.+)$",
    "firmware_version": r"^(?:Firmware Version|Revision):\s+(.+)$",
}
_ATTR_LINE = re.compile(
    r"^\s*(\d{1,3})\s+(\S+)\s+0x[0-9a-fA-F]+\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+\S+\s+(\S+)\s+(.+)$"
)


def smartctl_text_to_json(text: str) -> dict[str, Any]:
    """Pretvara tekst `smartctl -a` u strukturu nalik JSON izlazu, da bi važio isti parser."""
    data: dict[str, Any] = {"smartctl": {"exit_status": 0}, "device": {}}
    for line in text.splitlines():
        for key, pattern in _INFO_RE.items():
            m = re.match(pattern, line.strip())
            if m and key not in data:
                data[key] = m.group(1).strip()
        m = re.match(r"^User Capacity:\s+([\d,.\s]+) bytes", line.strip())
        if m:
            data["user_capacity"] = {"bytes": int(re.sub(r"\D", "", m.group(1)))}
        m = re.match(r"^Rotation Rate:\s+(.+)$", line.strip())
        if m:
            data["rotation_rate"] = 0 if "Solid State" in m.group(1) else int(re.sub(r"\D", "", m.group(1)) or 0)
        m = re.match(r"^LU WWN Device Id:\s+([0-9a-fA-F])\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)", line.strip())
        if m:
            data["wwn"] = {"naa": int(m.group(1), 16), "oui": int(m.group(2), 16), "id": int(m.group(3), 16)}
        m = re.match(r"^SMART overall-health self-assessment test result:\s+(\S+)", line.strip())
        if m:
            data["smart_status"] = {"passed": m.group(1) == "PASSED"}
        m = re.match(r"^SMART Health Status:\s+(\S+)", line.strip())  # SCSI
        if m:
            data["smart_status"] = {"passed": m.group(1) == "OK"}
        if "SMART support is: Unavailable" in line:
            data["smart_support"] = {"available": False, "enabled": False}
        if "SMART support is: Disabled" in line:
            data["smart_support"] = {"available": True, "enabled": False}
        if "Device is in STANDBY mode" in line or "Device is in SLEEP mode" in line:
            data["smartctl"] = {"exit_status": EXIT_OPEN_FAILED, "messages": [{"string": line.strip()}]}
        if line.startswith("NVMe Version"):
            data["device"]["protocol"] = "NVMe"
        m = _ATTR_LINE.match(line)
        if m:
            table = data.setdefault("ata_smart_attributes", {"table": []})["table"]
            table.append({
                "id": int(m.group(1)),
                "name": m.group(2),
                "value": int(m.group(3)),
                "worst": int(m.group(4)),
                "thresh": int(m.group(5)),
                "flags": {"prefailure": m.group(6) == "Pre-fail"},
                "when_failed": "" if m.group(7) == "-" else m.group(7),
                "raw": {"string": m.group(8).strip()},
            })
    if "ata_smart_attributes" in data and "protocol" not in data["device"]:
        data["device"]["protocol"] = "ATA"
    return data
