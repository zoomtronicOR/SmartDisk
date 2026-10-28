"""MQTT telemetrija i Home Assistant Discovery (spec. §12).

Jedna pozadinska veza ka brokeru: LWT i retain za dostupnost, periodični heartbeat, automatsko ponovno povezivanje.
Samo read-only telemetrija; komande se ne primaju. Serijski brojevi i SSH podaci se ne objavljuju.
"""

import asyncio
import json
import logging
import ssl
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from .. import __version__
from ..db import SessionLocal
from ..models import Device, Disk, DiskSample, Event, StoragePool, utcnow
from . import config

log = logging.getLogger("smartdisk.mqtt")

HEALTH_LABEL = {"excellent": "Odlično", "good": "Dobro", "attention": "Pažnja", "endangered": "Ugroženo",
                "critical": "Kritično", "unknown": "Nepoznato"}


class _State:
    task: asyncio.Task | None = None
    queue: asyncio.Queue | None = None
    connected: bool = False
    last_publish_at: datetime | None = None
    last_error: str | None = None
    config_snapshot: dict[str, Any] | None = None


state = _State()


def status() -> dict[str, Any]:
    return {"running": state.task is not None and not state.task.done(), "connected": state.connected,
            "last_publish_at": state.last_publish_at, "last_error": state.last_error}


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o))


async def build_state() -> dict[str, tuple[str, bool]]:
    """Sve poruke stanja: topic (bez prefiksa) → (payload, retain). Nedostupne vrednosti su null, nikad 0."""
    from ..routers.devices import device_status
    from ..routers.storage import disk_findings, last_smart_samples, standby_ids
    from ..scheduler import next_run_at

    messages: dict[str, tuple[str, bool]] = {}
    async with SessionLocal() as db:
        devices = list(await db.scalars(select(Device).where(Device.deleted_at.is_(None))))
        names = {d.id: d.name for d in devices}
        rows = (await db.execute(
            select(Disk, DiskSample).outerjoin(DiskSample, DiskSample.id == Disk.latest_sample_id)
            .where(Disk.device_id.in_(list(names)) if names else Disk.id < 0)
        )).all()
        last = await last_smart_samples(db, standby_ids(list(rows)))
        pools = list(await db.scalars(select(StoragePool).where(StoragePool.device_id.in_(list(names)) if names else StoragePool.id < 0,
                                                                StoragePool.is_present.is_(True))))
        alarms = dict((await db.execute(
            select(Event.severity, func.count()).where(Event.status.in_(("open", "acknowledged"))).group_by(Event.severity)
        )).all())
    now = utcnow()
    warn = 0
    for disk, sample in rows:
        s = last.get(disk.id) or sample
        state_, _ = disk_findings(sample, disk.is_present, last.get(disk.id))
        if disk.health_level in ("attention", "endangered", "critical"):
            warn += 1
        payload = {
            "device": names.get(disk.device_id), "device_id": disk.device_id, "disk": disk.device_path, "model": disk.model,
            "temperature_c": s.temperature_c if s else None,
            "smart_health": (s.smart_health.upper() if s and s.smart_health in ("passed", "failed") else (s.smart_health if s else None)),
            "disk_health": disk.health_level, "disk_health_label": HEALTH_LABEL.get(disk.health_level or "unknown"),
            "disk_health_score": disk.health_score,
            "disk_health_reasons": [r.get("rule") for r in disk.health_reasons or []],
            "power_on_hours": s.power_on_hours if s else None,
            "percentage_used": s.percentage_used if s else None,
            "present": disk.is_present, "standby": bool(sample and sample.smart_health == "standby"),
            "status": state_, "data_quality": "ok" if s and s.smart_available else "unavailable",
            "collected_at": s.collected_at if s else None,
        }
        messages[f"disks/{disk.id}/state"] = (_json(payload), True)
    for device in devices:
        nxt = next_run_at(device.id)
        messages[f"devices/{device.id}/state"] = (_json({
            "name": device.name, "platform": device.platform, "status": device_status(device),
            "last_success_at": device.last_success_at, "last_error": device.last_error, "next_run_at": nxt,
        }), True)
    for pool in pools:
        messages[f"pools/{pool.id}/state"] = (_json({
            "device": names.get(pool.device_id), "name": pool.name, "technology": pool.technology, "status": pool.status,
            "healthy": pool.healthy, "read_errors": pool.read_errors, "write_errors": pool.write_errors,
            "checksum_errors": pool.checksum_errors,
            "used_percent": round(100 * pool.used_bytes / pool.capacity_bytes, 1) if pool.used_bytes is not None and pool.capacity_bytes else None,
            "scan": pool.scan_state, "collected_at": pool.last_seen_at,
        }), True)
    last_success = max((d.last_success_at for d in devices if d.last_success_at), default=None)
    next_runs = [t for d in devices if (t := next_run_at(d.id))]
    messages["summary"] = (_json({
        "devices": len(devices), "devices_ok": sum(1 for d in devices if device_status(d) == "ok"),
        "disks": sum(1 for d, _ in rows if d.is_present), "disks_warning": warn,
        "alarms_critical": alarms.get("critical", 0), "alarms_high": alarms.get("high", 0),
        "alarms_warning": alarms.get("warning", 0),
        "last_collection_at": last_success, "next_collection_at": min(next_runs) if next_runs else None,
        "updated_at": now, "version": __version__,
    }), True)
    messages["_entities"] = (_json({
        "devices": [{"id": d.id, "name": d.name, "platform": d.platform} for d in devices],
        "disks": [{"id": d.id, "device_id": d.device_id, "path": d.device_path, "model": d.model, "type": d.disk_type}
                  for d, _ in rows if d.is_present],
        "pools": [{"id": p.id, "device_id": p.device_id, "name": p.name, "technology": p.technology} for p in pools],
    }), False)
    return messages


def discovery(cfg: dict[str, Any], entities: dict[str, Any]) -> dict[str, str]:
    """Home Assistant MQTT Discovery konfiguracije (topic → payload; prazan payload briše entitet)."""
    prefix, dp = cfg["prefix"], cfg["discovery_prefix"]
    enabled = set(cfg.get("entities") or [])
    avail = {"availability_topic": f"{prefix}/availability", "payload_available": "online", "payload_not_available": "offline"}
    app_device = {"identifiers": ["smartdisk"], "name": "SmartDisk", "manufacturer": "SmartDisk", "sw_version": __version__}
    out: dict[str, str] = {}

    def entity(kind: str, component: str, uid: str, payload: dict[str, Any]) -> None:
        topic = f"{dp}/{component}/{uid}/config"
        out[topic] = _json({**payload, "unique_id": uid, "object_id": uid, **avail}) if kind in enabled else ""

    summary_topic = f"{prefix}/summary"
    for key, name, extra in (
        ("devices", "Nadzirani uređaji", {}), ("disks", "Diskovi", {}), ("disks_warning", "Diskovi sa upozorenjem", {}),
        ("alarms_critical", "Kritični alarmi", {}), ("alarms_high", "Visoki alarmi", {}),
        ("last_collection_at", "Poslednje prikupljanje", {"device_class": "timestamp"}),
        ("next_collection_at", "Sledeće prikupljanje", {"device_class": "timestamp"}),
    ):
        entity("summary", "sensor", f"smartdisk_{key}", {
            "name": name, "state_topic": summary_topic, "value_template": f"{{{{ value_json.{key} }}}}",
            "device": app_device, **extra,
        })
    for dev in entities["devices"]:
        ha_dev = {"identifiers": [f"smartdisk_device_{dev['id']}"], "name": f"SmartDisk - {dev['name']}",
                  "manufacturer": "SmartDisk", "model": dev["platform"], "via_device": "smartdisk"}
        entity("device_status", "sensor", f"smartdisk_device_{dev['id']}_status", {
            "name": "Status uređaja", "state_topic": f"{prefix}/devices/{dev['id']}/state",
            "value_template": "{{ value_json.status }}", "json_attributes_topic": f"{prefix}/devices/{dev['id']}/state",
            "device": ha_dev, "icon": "mdi:server",
        })
    dev_names = {d["id"]: d["name"] for d in entities["devices"]}
    for disk in entities["disks"]:
        ha_dev = {"identifiers": [f"smartdisk_device_{disk['device_id']}"], "name": f"SmartDisk - {dev_names.get(disk['device_id'])}"}
        base = f"{prefix}/disks/{disk['id']}/state"
        label = f"{disk['path']} {disk.get('model') or ''}".strip()
        uid = f"smartdisk_disk_{disk['id']}"
        entity("disk_temperature", "sensor", f"{uid}_temperature", {
            "name": f"{label} temperatura", "state_topic": base, "value_template": "{{ value_json.temperature_c }}",
            "unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement", "device": ha_dev,
        })
        entity("disk_smart", "sensor", f"{uid}_smart", {
            "name": f"{label} SMART", "state_topic": base, "value_template": "{{ value_json.smart_health }}",
            "device": ha_dev, "icon": "mdi:harddisk",
        })
        entity("disk_health", "sensor", f"{uid}_health", {
            "name": f"{label} zdravlje", "state_topic": base, "value_template": "{{ value_json.disk_health_label }}",
            "json_attributes_topic": base, "device": ha_dev, "icon": "mdi:heart-pulse",
        })
        entity("disk_poh", "sensor", f"{uid}_poh", {
            "name": f"{label} sati rada", "state_topic": base, "value_template": "{{ value_json.power_on_hours }}",
            "unit_of_measurement": "h", "state_class": "total_increasing", "device": ha_dev, "icon": "mdi:timer-outline",
        })
        if disk["type"] == "nvme":
            entity("disk_wear", "sensor", f"{uid}_wear", {
                "name": f"{label} istrošenost", "state_topic": base, "value_template": "{{ value_json.percentage_used }}",
                "unit_of_measurement": "%", "state_class": "measurement", "device": ha_dev, "icon": "mdi:gauge",
            })
    for pool in entities["pools"]:
        if pool["technology"] not in ("zfs", "mdadm", "lvm_thin", "synology_volume"):
            continue
        ha_dev = {"identifiers": [f"smartdisk_device_{pool['device_id']}"], "name": f"SmartDisk - {dev_names.get(pool['device_id'])}"}
        base = f"{prefix}/pools/{pool['id']}/state"
        uid = f"smartdisk_pool_{pool['id']}"
        entity("pool_status", "sensor", f"{uid}_status", {
            "name": f"{pool['name']} status", "state_topic": base, "value_template": "{{ value_json.status }}",
            "json_attributes_topic": base, "device": ha_dev, "icon": "mdi:database",
        })
        if pool["technology"] == "zfs":
            entity("pool_errors", "sensor", f"{uid}_errors", {
                "name": f"{pool['name']} greške (R+W+CKSUM)", "state_topic": base,
                "value_template": "{{ (value_json.read_errors or 0) + (value_json.write_errors or 0) + (value_json.checksum_errors or 0) }}",
                "state_class": "measurement", "device": ha_dev, "icon": "mdi:alert-circle-outline",
            })
    return out


def publish_state() -> None:
    """Zahtev za objavu trenutnog stanja (posle ciklusa prikupljanja)."""
    if state.queue is not None:
        try:
            state.queue.put_nowait(("state", None))
        except asyncio.QueueFull:
            pass


def publish_event(payload: dict[str, Any]) -> None:
    if state.queue is not None:
        try:
            state.queue.put_nowait(("event", payload))
        except asyncio.QueueFull:
            log.warning("MQTT red je pun - događaj nije objavljen")


def _tls(cfg: dict[str, Any]) -> ssl.SSLContext | None:
    if not cfg.get("tls"):
        return None
    ctx = ssl.create_default_context()
    if cfg.get("tls_insecure"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def _run(cfg: dict[str, Any]) -> None:
    import aiomqtt

    prefix = cfg["prefix"].strip("/")
    qos = int(cfg.get("qos", 1))
    retain = bool(cfg.get("retain", True))
    delay = 5
    published_discovery: set[str] = set()
    while True:
        try:
            will = aiomqtt.Will(f"{prefix}/availability", "offline", qos=1, retain=True)
            async with aiomqtt.Client(
                hostname=cfg["host"], port=int(cfg["port"]), username=cfg.get("username") or None,
                password=config.password(cfg), identifier=cfg.get("client_id") or "smartdisk", will=will,
                tls_context=_tls(cfg), keepalive=60, timeout=15,
            ) as client:
                state.connected = True
                state.last_error = None
                delay = 5
                log.info("MQTT povezan na %s:%s", cfg["host"], cfg["port"])
                await client.publish(f"{prefix}/availability", "online", qos=1, retain=True)

                async def publish_all() -> None:
                    messages = await build_state()
                    entities = json.loads(messages.pop("_entities")[0])
                    for topic, (payload, keep) in messages.items():
                        await client.publish(f"{prefix}/{topic}", payload, qos=qos, retain=retain and keep)
                    if cfg.get("discovery"):
                        configs = discovery(cfg, entities)
                        for topic, payload in configs.items():
                            if payload or topic in published_discovery:
                                await client.publish(topic, payload, qos=1, retain=True)
                            if payload:
                                published_discovery.add(topic)
                    state.last_publish_at = utcnow()

                await publish_all()
                heartbeat = max(10, int(cfg.get("heartbeat_seconds", 60)))
                while True:
                    try:
                        kind, payload = await asyncio.wait_for(state.queue.get(), timeout=heartbeat)
                    except TimeoutError:
                        kind, payload = "state", None
                    if kind == "event":
                        await client.publish(f"{prefix}/events", _json(payload), qos=1, retain=False)
                        state.last_publish_at = utcnow()
                    else:
                        await publish_all()
        except asyncio.CancelledError:
            state.connected = False
            raise
        except Exception as exc:  # broker nedostupan, odbijena prijava…
            state.connected = False
            state.last_error = _error_text(exc)
            log.warning("MQTT: %s - novi pokušaj za %s s", state.last_error, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)


def _error_text(exc: Exception) -> str:
    text = str(exc)
    if "Not authorized" in text or "authoriz" in text.lower() or "code:5" in text or "code:135" in text:
        return "Broker je odbio prijavu (korisničko ime/lozinka)."
    if "Connection refused" in text or "Errno 111" in text:
        return "Broker odbija vezu (proverite adresu i port)."
    if "timed out" in text.lower():
        return "Isteklo je vreme za povezivanje sa brokerom."
    return f"Greška MQTT veze: {text}"


async def restart() -> None:
    """(Ponovo) pokreće vezu prema trenutnim podešavanjima; zaustavlja je ako je MQTT isključen."""
    if state.task is not None:
        state.task.cancel()
        try:
            await state.task
        except (asyncio.CancelledError, Exception):
            pass
        state.task = None
    state.connected = False
    async with SessionLocal() as db:
        cfg = await config.load(db, config.MQTT)
    state.config_snapshot = cfg
    if not cfg.get("enabled") or not cfg.get("host"):
        state.queue = None
        return
    state.queue = asyncio.Queue(maxsize=1000)
    state.task = asyncio.create_task(_run(cfg), name="mqtt")


async def stop() -> None:
    if state.task is not None:
        state.task.cancel()
        try:
            await state.task
        except (asyncio.CancelledError, Exception):
            pass


async def test_connection(cfg: dict[str, Any]) -> None:
    """Jednokratna provera veze i prijave (bez objave)."""
    import aiomqtt

    try:
        async with aiomqtt.Client(
            hostname=cfg["host"], port=int(cfg["port"]), username=cfg.get("username") or None,
            password=config.password(cfg), identifier=f"{cfg.get('client_id') or 'smartdisk'}-test",
            tls_context=_tls(cfg), timeout=10,
        ):
            pass
    except Exception as exc:
        raise ValueError(_error_text(exc)) from exc
