"""Ciklus prikupljanja za jedan uređaj.

Jedna SSH konekcija po ciklusu: provera host ključa, detekcija sistema i alata, zatim platformski adapter
(TrueNAS, Proxmox, Synology) za diskove, SMART i stanje skladišta. Rezultat se čuva u bazi.
"""

import asyncio
import logging
import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from . import crypto
from .adapters import platforms
from .adapters.model import CollectResult
from .config import get_settings
from .db import SessionLocal
from .models import CollectionRun, Device, DeviceCapability, Disk, DiskSample, utcnow
from .persist import save_disks, save_pools
from . import events, health
from .notify import config as notify_config
from .notify import dispatcher, mqtt
from .ssh.client import ConnInfo, SSHError, connect, run_command
from .ssh.probe import PROBE_COMMAND, TOOLS, parse_probe

log = logging.getLogger("smartdisk.collector")

_semaphore: asyncio.Semaphore | None = None
_running: set[int] = set()


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().max_parallel_ssh)
    return _semaphore


def is_running(device_id: int) -> bool:
    return device_id in _running


def is_ready(device: Device) -> bool:
    """Uređaj može da se kontaktira tek kada ima kredencijale i potvrđen host ključ."""
    return bool(device.encrypted_private_key and device.host_key and device.host_key_confirmed_at)


async def run_collection(device_id: int, trigger: str, initiated_by: str | None = None) -> int | None:
    """Izvršava jedan ciklus i vraća id zapisa u collection_runs (ili None ako ciklus nije pokrenut)."""
    if device_id in _running:
        log.info("Prikupljanje za uređaj %s je već u toku, preskačem (%s)", device_id, trigger)
        return None
    _running.add(device_id)
    try:
        async with _sem():
            return await _collect(device_id, trigger, initiated_by)
    finally:
        _running.discard(device_id)


async def _collect(device_id: int, trigger: str, initiated_by: str | None) -> int | None:
    async with SessionLocal() as db:
        device = await db.get(Device, device_id)
        if device is None or device.deleted_at is not None:
            return None
        if trigger == "scheduled" and not device.enabled:
            return None
        run = CollectionRun(
            device_id=device.id,
            trigger=trigger,
            started_at=utcnow(),
            status="running",
            errors_count=0,
            initiated_by=initiated_by,
        )
        db.add(run)
        await db.commit()
        run_id = run.id
        platform = device.platform
        command_timeout = device.command_timeout
        use_sudo = device.ssh_username != "root"
        # Test konekcije proverava samo pristup i alate; prikupljanje radi ceo ciklus.
        full = trigger != "test"
        info: ConnInfo | None = None
        error: SSHError | None = None
        if not is_ready(device):
            error = SSHError("not_configured", "Uređaj nema SSH ključ ili potvrđen host ključ.")
        else:
            try:
                info = ConnInfo(
                    host=device.host,
                    port=device.ssh_port,
                    username=device.ssh_username,
                    private_key=crypto.decrypt(device.encrypted_private_key or ""),
                    passphrase=crypto.decrypt(device.encrypted_passphrase) if device.encrypted_passphrase else None,
                    host_key=device.host_key or "",
                    connect_timeout=device.connect_timeout,
                )
            except ValueError as exc:
                error = SSHError("credentials", str(exc))

    # SSH deo se radi bez otvorene DB sesije.
    started = time.monotonic()
    probe = None
    clock_offset: int | None = None
    collected: CollectResult | None = None
    if info is not None:
        try:
            async with connect(info) as conn:
                sent = time.time()
                result = await run_command(conn, PROBE_COMMAND, command_timeout)
                received = time.time()
                probe = parse_probe(result.stdout, platform)
                if probe.device_epoch is not None:
                    # Odstupanje sata uređaja (±1 s zbog celih sekundi i trajanja komande)
                    clock_offset = probe.device_epoch - round((sent + received) / 2)
                if full:
                    collected = await platforms.collect(
                        platform,
                        lambda cmd: run_command(conn, cmd, command_timeout),
                        probe.tools,
                        use_sudo,
                        probe.smartctl_version,
                    )
        except SSHError as exc:
            error = exc
        except Exception:
            log.exception("Neočekivana greška pri prikupljanju za uređaj %s", device_id)
            error = SSHError("unexpected", "Neočekivana greška u collector-u (detalji su u logu servisa).")
    duration_ms = int((time.monotonic() - started) * 1000)

    async with SessionLocal() as db:
        now = utcnow()
        run = await db.get(CollectionRun, run_id)
        device = await db.get(Device, device_id)
        if run is None or device is None:
            return run_id
        run.finished_at = now
        run.duration_ms = duration_ms
        if error is not None:
            run.status = "failed"
            run.errors_count = 1
            run.error_kind = error.kind
            run.error_message = error.message
            device.last_failure_at = now
            device.last_error = error.message
            log.warning("Uređaj %s (%s): %s", device.name, trigger, error.message)
        elif probe is not None:
            run.status = "success"
            run.details = {
                "os_info": probe.os_info,
                "detected_platform": probe.detected_platform,
                "smartctl_version": probe.smartctl_version,
                "warnings": probe.warnings,
                "clock_offset_s": clock_offset,
            }
            if collected is not None:
                disk_ids = await save_disks(db, device_id, run_id, collected, now)
                await save_pools(db, device_id, collected, disk_ids, now)
                run.disks_found = len(collected.disks)
                run.errors_count = len(collected.errors)
                run.details = {
                    **run.details,
                    "pools_found": len(collected.pools),
                    "errors": collected.errors,
                    "warnings": probe.warnings + collected.warnings,
                }
                if collected.errors:
                    run.status = "partial"
                    run.error_kind = "partial"
                    run.error_message = " ".join(collected.errors)[:2000]
            device.os_info = probe.os_info
            device.last_seen_at = now
            device.last_success_at = now
            device.last_error = None
            for tool, path in probe.tools.items():
                details = path or "Nije pronađen"
                if tool == "smartctl" and probe.smartctl_version:
                    details = f"{path} – {probe.smartctl_version}"
                stmt = insert(DeviceCapability).values(
                    device_id=device_id, capability=tool, available=bool(path), details=details, checked_at=now
                )
                await db.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["device_id", "capability"],
                        set_={"available": stmt.excluded.available, "details": stmt.excluded.details,
                              "checked_at": stmt.excluded.checked_at},
                    )
                )
        await db.commit()

    # Procena zdravlja i alarma (Faza 4). Test konekcije ne menja alarme. Greška ovde ne sme oboriti ciklus.
    if trigger != "test":
        try:
            await _evaluate(device_id, collected is not None and error is None,
                            collected.changes if collected is not None and error is None else [])
        except Exception:
            log.exception("Procena zdravlja i alarma za uređaj %s nije uspela", device_id)
    return run_id


async def _evaluate(device_id: int, collected: bool, changes: list[dict] | None = None) -> None:
    async with SessionLocal() as db:
        device = await db.get(Device, device_id)
        if device is None:
            return
        th = await notify_config.thresholds(db)
        open_fps = await events.open_fingerprints(db, device_id)
        evaluation = await health.evaluate_device(db, device, th, open_fps, collected)
        # Promene inventara (spec. §16.2) su pojedinačni događaji: svaki je poseban alarm koji ostaje do potvrde.
        stamp = utcnow().strftime("%Y%m%d%H%M%S")
        for ch in changes or []:
            target = f"disk:{ch['disk_id']}" if ch.get("disk_id") else f"pool:{ch.get('pool_id')}"
            evaluation.conditions.append(health.Condition(
                f"{target}:{ch['rule']}:{stamp}", "info" if ch["rule"] == "disk_added" else "warning", "inventory",
                ch["rule"], f"{device.name}: {ch['title']}", ch["message"], device.id,
                disk_id=ch.get("disk_id"), pool_id=ch.get("pool_id"),
            ))
        now = utcnow()
        if evaluation.health:
            disks = {d.id: d for d in await db.scalars(select(Disk).where(Disk.id.in_(list(evaluation.health))))}
            for disk_id, h in evaluation.health.items():
                disk = disks.get(disk_id)
                if disk is None:
                    continue
                disk.health_level = h.level
                disk.health_score = h.score
                disk.health_reasons = h.reasons
                disk.health_updated_at = now
                if disk.latest_sample_id:
                    sample = await db.get(DiskSample, disk.latest_sample_id)
                    if sample is not None:
                        sample.health_level = h.level
                        sample.health_score = h.score
        notices = await events.apply(db, device_id, evaluation, th)
        await db.commit()
    await dispatcher.dispatch(notices)
    mqtt.publish_state()


async def capabilities_for(device_id: int) -> list[DeviceCapability]:
    async with SessionLocal() as db:
        rows = await db.scalars(select(DeviceCapability).where(DeviceCapability.device_id == device_id))
        order = list(TOOLS)
        return sorted(rows, key=lambda c: order.index(c.capability) if c.capability in order else 99)
