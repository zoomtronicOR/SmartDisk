"""Planiranje prikupljanja. Svaki uključen uređaj ima svoj posao; promena intervala važi odmah, bez restarta.

Scheduler radi u istom procesu kao API, zato uvicorn mora raditi sa jednim worker-om.
"""

import logging
import random
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select

from . import analytics, settings_store
from .collector import is_ready, run_collection
from .db import SessionLocal
from .models import Device, DiskSample, PoolSample, UserSession, utcnow

log = logging.getLogger("smartdisk.scheduler")

scheduler = AsyncIOScheduler(
    timezone="UTC",
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
)

HEARTBEAT_SECONDS = 30
_last_heartbeat: datetime | None = None


def _job_id(device_id: int) -> str:
    return f"collect:{device_id}"


def _heartbeat() -> None:
    global _last_heartbeat
    _last_heartbeat = utcnow()


def scheduler_healthy() -> bool:
    if not scheduler.running or _last_heartbeat is None:
        return False
    return utcnow() - _last_heartbeat < timedelta(seconds=HEARTBEAT_SECONDS * 3)


def last_heartbeat() -> datetime | None:
    return _last_heartbeat


def next_run_at(device_id: int) -> datetime | None:
    job = scheduler.get_job(_job_id(device_id))
    return job.next_run_time if job else None


def job_count() -> int:
    return len([j for j in scheduler.get_jobs() if j.id.startswith("collect:")])


async def _scheduled_collect(device_id: int) -> None:
    await run_collection(device_id, "scheduled")
    # Posao čiji uređaj više ne postoji ili je isključen van API-ja (npr. direktno u bazi) se uklanja.
    async with SessionLocal() as db:
        device = await db.get(Device, device_id)
        if device is None or device.deleted_at is not None or not device.enabled:
            job = scheduler.get_job(_job_id(device_id))
            if job:
                job.remove()
                log.info("Uklonjen posao za nepostojeći ili isključen uređaj %s", device_id)


def sync_device(device: Device, default_interval: int, first_run_delay: float = 10) -> None:
    """Usklađuje posao uređaja sa njegovim stanjem u bazi."""
    job_id = _job_id(device.id)
    job = scheduler.get_job(job_id)
    should_run = device.enabled and device.deleted_at is None and is_ready(device)
    if not should_run:
        if job:
            job.remove()
            log.info("Uklonjen posao za uređaj %s", device.name)
        return

    minutes = device.collection_interval_minutes or default_interval
    interval = timedelta(minutes=minutes)
    if job is None:
        scheduler.add_job(
            _scheduled_collect,
            IntervalTrigger(minutes=minutes),
            id=job_id,
            args=[device.id],
            next_run_time=utcnow() + timedelta(seconds=first_run_delay),
        )
        log.info("Dodat posao za uređaj %s, interval %s min", device.name, minutes)
    elif job.trigger.interval != interval:
        # Novi interval odmah važi: sledeći ciklus je "sada + novi interval".
        job.reschedule(IntervalTrigger(minutes=minutes))
        log.info("Promenjen interval za uređaj %s na %s min", device.name, minutes)


async def sync_all() -> None:
    async with SessionLocal() as db:
        default_interval = await settings_store.get_setting(db, settings_store.DEFAULT_INTERVAL)
        devices = (await db.scalars(select(Device).where(Device.deleted_at.is_(None)))).all()
    for device in devices:
        # Pri startu rasporediti prve cikluse da se uređaji ne kontaktiraju istovremeno.
        sync_device(device, default_interval, first_run_delay=random.uniform(5, 60))


async def _cleanup_sessions() -> None:
    async with SessionLocal() as db:
        await db.execute(delete(UserSession).where(UserSession.expires_at < utcnow()))
        await db.commit()


async def _aggregate_daily() -> None:
    """Dnevni agregati za završene dane; ostaju i kada se sirova merenja obrišu (spec. §9.2)."""
    async with SessionLocal() as db:
        await analytics.aggregate_daily(db)
        await db.commit()
    log.info("Dnevni agregati su ažurirani")


async def _check_time() -> None:
    """NTP provera i sistemski alarmi za vreme (spec. §18.1)."""
    from . import events, health, timesync
    from .notify import config as notify_config
    from .notify import dispatcher

    async with SessionLocal() as db:
        server = await settings_store.get_setting(db, settings_store.NTP_SERVER)
    st = await timesync.check(server)
    async with SessionLocal() as db:
        th = await notify_config.thresholds(db)
        conds = health.system_conditions(timesync.status(), th)
        evaluation = health.Evaluation(conds, {}, {"ntp_unreachable", "time_offset", "time_unsynced"})
        notices = await events.apply(db, None, evaluation, th)
        await db.commit()
    await dispatcher.dispatch(notices)
    log.debug("NTP provera: odstupanje %s ms, greška: %s", st.offset_ms, st.error)


async def _hourly() -> None:
    """Zakazani izveštaji i dnevni backup (proverava se svakog sata)."""
    from . import events, health, schedules
    from .notify import config as notify_config
    from .notify import dispatcher
    from .routers.advanced import backup_settings, run_backup

    try:
        await schedules.run_due()
    except Exception:
        log.exception("Zakazani izveštaji nisu obrađeni")
    async with SessionLocal() as db:
        cfg = await backup_settings(db)
        tz = await settings_store.get_setting(db, settings_store.TIMEZONE)
    from zoneinfo import ZoneInfo

    now_local = datetime.now(ZoneInfo(tz))
    last = (cfg.get("last") or {}).get("finished_at")
    done_today = last and datetime.fromisoformat(last).astimezone(now_local.tzinfo).date() == now_local.date()
    if not cfg.get("enabled") or now_local.hour != int(cfg.get("hour", 2)) or done_today:
        return
    info = await run_backup("scheduler")
    async with SessionLocal() as db:
        th = await notify_config.thresholds(db)
        conds = []
        if info["status"] != "ok":
            conds.append(health.Condition("system:backup_failed", "high", "system", "backup_failed",
                                          "Backup baze nije uspeo", info.get("error") or "Nepoznata greška.", None))
        notices = await events.apply(db, None, health.Evaluation(conds, {}, {"backup_failed"}), th)
        await db.commit()
    await dispatcher.dispatch(notices)


async def _cleanup_samples() -> None:
    """Brisanje sirovih merenja starijih od podešenog perioda (podrazumevano 12 meseci)."""
    async with SessionLocal() as db:
        days = await settings_store.get_setting(db, settings_store.RAW_RETENTION_DAYS)
        cutoff = utcnow() - timedelta(days=days)
        disks = await db.execute(delete(DiskSample).where(DiskSample.collected_at < cutoff))
        pools = await db.execute(delete(PoolSample).where(PoolSample.collected_at < cutoff))
        await db.commit()
    if disks.rowcount or pools.rowcount:
        log.info("Obrisano starih merenja: diskovi %s, pool-ovi %s (starije od %s dana)",
                 disks.rowcount, pools.rowcount, days)


async def start() -> None:
    _heartbeat()
    scheduler.add_job(_heartbeat, "interval", seconds=HEARTBEAT_SECONDS, id="heartbeat", replace_existing=True)
    scheduler.add_job(_cleanup_sessions, "interval", hours=1, id="cleanup_sessions", replace_existing=True)
    scheduler.add_job(_aggregate_daily, "cron", hour=3, minute=15, id="aggregate_daily", replace_existing=True)
    scheduler.add_job(_check_time, "interval", minutes=15, id="check_time", replace_existing=True,
                      next_run_time=utcnow() + timedelta(seconds=20))
    scheduler.add_job(_cleanup_samples, "cron", hour=3, minute=30, id="cleanup_samples", replace_existing=True)
    scheduler.add_job(_hourly, "cron", minute=5, id="hourly", replace_existing=True)
    scheduler.start()
    await sync_all()
    log.info("Scheduler pokrenut, poslova prikupljanja: %s", job_count())


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
