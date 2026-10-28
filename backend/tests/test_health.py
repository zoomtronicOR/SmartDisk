"""Testovi degradacije (spec. §21.2): simulirani rast grešaka, eskalacija i zdravlje diska."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.health import DEFAULT_THRESHOLDS, correlate, disk_health, evaluate_disk, evaluate_pool, merge_thresholds

TH = merge_thresholds(None)
DEVICE = SimpleNamespace(id=1, name="TrueNAS")
NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)

SAMPLE_FIELDS = ["reallocated_sectors", "pending_sectors", "uncorrectable_sectors", "reported_uncorrect", "crc_errors",
                 "media_errors", "error_log_entries", "unsafe_shutdowns", "available_spare", "available_spare_threshold",
                 "percentage_used", "ssd_life_left", "critical_warning", "warning_temp_time", "critical_temp_time",
                 "temperature_c", "power_on_hours", "smart_message"]


def disk(disk_type="hdd", present=True, id=10):
    return SimpleNamespace(id=id, device_id=1, device_path="/dev/sdb", model="WDC WD4003FRYZ", disk_type=disk_type,
                           is_present=present, last_seen_at=NOW)


def sample(**kw):
    base = {f: None for f in SAMPLE_FIELDS}
    base.update(smart_available=True, smart_health="passed", temperature_c=35, power_on_hours=10_000)
    if "smart_health" in kw and kw["smart_health"] in ("unavailable", "standby"):
        base["smart_available"] = False
    base.update(kw)
    return SimpleNamespace(**base)


def hist(**kw):
    """kw: reallocated_sectors=(d1, d7, d30) - vrednosti na početku prozora; prev_<col>=…; temps=[…]."""
    h = {}
    for key, value in kw.items():
        if key == "temps":
            h["temps_24h"] = value
        elif key == "recent":
            h["recent_available"] = value
        elif key.startswith("prev_"):
            h[f"{key[5:]}__prev"] = value
        else:
            d1, d7, d30 = value
            h[f"{key}__d1"], h[f"{key}__d7"], h[f"{key}__d30"] = d1, d7, d30
    return h


def run(s, h=None, d=None, open_fps=frozenset()):
    d = d or disk()
    conds = evaluate_disk(DEVICE, d, s, None, h or {}, TH, set(open_fps))
    return conds, disk_health(d, s, None, conds)


def by_rule(conds):
    return {c.rule: c for c in conds}


def test_healthy_disk_is_excellent():
    conds, h = run(sample(reallocated_sectors=0, pending_sectors=0))
    assert conds == [] and h.level == "excellent" and h.score == 100


def test_passed_but_growing_reallocated_is_endangered():
    """SMART PASSED, ali rast realociranih sektora → zdravlje niže od „Dobro” (spec. §8.8, §21.4 tačka 8)."""
    conds, h = run(sample(reallocated_sectors=24), hist(reallocated_sectors=(18, 12, 12)))
    c = by_rule(conds)["reallocated"]
    assert c.severity == "high"  # +6 u 24 h ≥ 5
    assert h.level == "endangered" and "+6" in c.message and "+12" in c.message


def test_reallocated_escalation_levels():
    stable = by_rule(run(sample(reallocated_sectors=8), hist(reallocated_sectors=(8, 8, 8)))[0])["reallocated"]
    slow = by_rule(run(sample(reallocated_sectors=9), hist(reallocated_sectors=(8, 8, 8)))[0])["reallocated"]
    fast = by_rule(run(sample(reallocated_sectors=20), hist(reallocated_sectors=(19, 9, 9)))[0])["reallocated"]
    assert (stable.severity, slow.severity, fast.severity) == ("info", "warning", "high")


def test_pending_growth():
    conds, h = run(sample(pending_sectors=8), hist(pending_sectors=(4, 0, 0)))
    assert by_rule(conds)["pending"].severity == "high" and h.level == "endangered"
    conds, _ = run(sample(pending_sectors=1), hist(pending_sectors=(1, 1, 1)))
    assert by_rule(conds)["pending"].severity == "warning"


def test_uncorrectable_growth_is_critical():
    conds, h = run(sample(uncorrectable_sectors=3), hist(uncorrectable_sectors=(0, 0, 0)))
    assert by_rule(conds)["uncorrectable_sectors"].severity == "critical" and h.level == "critical"


def test_nvme_media_errors_increase_between_readings():
    conds, _ = run(sample(media_errors=5), hist(media_errors=(4, 4, 4), prev_media_errors=4), disk("nvme"))
    assert by_rule(conds)["media_errors"].severity == "high"


def test_nvme_spare_below_threshold_and_critical_warning():
    conds, h = run(sample(available_spare=8, available_spare_threshold=10, critical_warning=1), None, disk("nvme"))
    rules = by_rule(conds)
    assert rules["available_spare"].severity == "critical"
    assert rules["nvme_critical_warning"].severity == "critical"
    assert h.level == "critical"


def test_nvme_percentage_used_thresholds():
    assert by_rule(run(sample(percentage_used=85), None, disk("nvme"))[0])["percentage_used"].severity == "warning"
    assert by_rule(run(sample(percentage_used=95), None, disk("nvme"))[0])["percentage_used"].severity == "high"
    assert "percentage_used" not in by_rule(run(sample(percentage_used=30), None, disk("nvme"))[0])


def test_temperature_levels_and_repeat():
    assert by_rule(run(sample(temperature_c=48))[0])["temperature"].severity == "info"
    assert by_rule(run(sample(temperature_c=51), hist(temps=[40, 41]))[0])["temperature"].severity == "warning"
    assert by_rule(run(sample(temperature_c=51), hist(temps=[51, 52, 50, 49]))[0])["temperature"].severity == "high"
    assert by_rule(run(sample(temperature_c=56))[0])["temperature"].severity == "critical"
    # NVMe ima više pragove
    assert "temperature" not in by_rule(run(sample(temperature_c=60), None, disk("nvme"))[0])


def test_temperature_hysteresis_keeps_alarm_open():
    fp = "disk:10:temperature"
    conds, _ = run(sample(temperature_c=49), hist(temps=[51]), open_fps={fp})
    assert by_rule(conds)["temperature"].severity == "warning"  # 49 ≥ 50 − 2: alarm ostaje
    conds, _ = run(sample(temperature_c=46), hist(temps=[51]), open_fps={fp})
    assert "temperature" not in by_rule(conds)


def test_temperature_jump():
    conds, _ = run(sample(temperature_c=45), hist(temps=[33, 35, 40]))
    assert by_rule(conds)["temperature_jump"].severity == "info"


def test_smart_failed():
    conds, h = run(sample(smart_health="failed"))
    assert by_rule(conds)["smart_failed"].severity == "critical" and h.level == "critical"


def test_no_data_is_unknown_never_ok():
    s = sample(smart_health="unavailable", smart_message="Kontroler ne prosleđuje SMART.")
    conds, h = run(s, hist(recent=[False, False, False, True]))
    assert h.level == "unknown" and h.score is None
    assert by_rule(conds)["no_data"].severity == "warning"
    conds, h = run(s, hist(recent=[False, True]))  # samo jedan ciklus bez podataka - još bez alarma
    assert "no_data" not in by_rule(conds) and h.level == "unknown"


def test_missing_disk():
    d = disk(present=False)
    conds, h = run(sample(), None, d)
    assert by_rule(conds)["disk_missing"].severity == "high" and h.level == "unknown"


def test_crc_is_informational():
    conds, h = run(sample(crc_errors=3), hist(crc_errors=(2, 1, 1)))
    assert by_rule(conds)["crc_errors"].severity == "info" and h.level == "good"


def pool(**kw):
    base = dict(id=5, name="tank", technology="zfs", status="ONLINE", healthy=True, is_present=True, read_errors=0,
                write_errors=0, checksum_errors=0, members=[], scan_state="finished", scan_errors=0, scan_type="scrub",
                scan_finished_at="Sun Oct 4 2026", used_bytes=50, capacity_bytes=100, message=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_pool_degraded_and_correlation():
    """Degradiran ZFS pool + disk sa SMART problemom u istom vdev-u → kritično (spec. §8.7)."""
    members = [{"name": "/dev/sdb1", "kind": "disk", "state": "FAULTED", "disk_id": 10, "disk_path": "sdb"},
               {"name": "/dev/sdc1", "kind": "disk", "state": "ONLINE", "disk_id": 11, "disk_path": "sdc"}]
    p = pool(status="DEGRADED", healthy=False, members=members)
    pool_conds = evaluate_pool(DEVICE, p, TH, set())
    assert by_rule(pool_conds)["pool_unhealthy"].severity == "high"
    assert "sdb" in by_rule(pool_conds)["pool_unhealthy"].message
    d = disk()
    disk_conds, _ = run(sample(pending_sectors=4), hist(pending_sectors=(4, 4, 4)), d)
    corr = correlate(DEVICE, [p], disk_conds + pool_conds, {10: d})
    assert len(corr) == 1 and corr[0].severity == "critical" and "DEGRADED" in corr[0].message
    h = disk_health(d, sample(pending_sectors=4), None, disk_conds + corr)
    assert h.level == "critical"


def test_pool_usage_scrub_and_errors():
    conds = by_rule(evaluate_pool(DEVICE, pool(used_bytes=92, checksum_errors=3, scan_errors=2), TH, set()))
    assert conds["pool_usage"].severity == "high"
    assert conds["pool_errors"].severity == "warning"
    assert conds["scrub_errors"].severity == "high"
    assert evaluate_pool(DEVICE, pool(), TH, set()) == []
    # LVM volume grupa je uvek skoro puna (thin pool) - nije alarm
    assert evaluate_pool(DEVICE, pool(technology="lvm_vg", used_bytes=99), TH, set()) == []


def test_thresholds_merge():
    th = merge_thresholds({"temperature": {"hdd": {"warning": 45}}, "reallocated_high_24h": 1, "unknown_key": 5})
    assert th["temperature"]["hdd"] == {"info": 47, "warning": 45, "critical": 55}
    assert th["temperature"]["nvme"] == DEFAULT_THRESHOLDS["temperature"]["nvme"]
    assert th["reallocated_high_24h"] == 1 and "unknown_key" not in th
