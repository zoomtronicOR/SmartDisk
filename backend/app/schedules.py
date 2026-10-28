"""Zakazani izveštaji (spec. §10.7, §22 Faza 5): izveštaj u prilogu e-pošte, dnevno/nedeljno/mesečno."""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import export, reports, settings_store
from .db import SessionLocal
from .notify import config, email
from .models import NotificationLog

log = logging.getLogger("smartdisk.schedules")

KEY = "reports.schedules"
PERIOD_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def due(schedule: dict[str, Any], now_local: datetime) -> bool:
    """Da li raspored treba poslati u ovom satu (provera se radi jednom na sat)."""
    if not schedule.get("enabled") or now_local.hour != int(schedule.get("hour", 7)):
        return False
    period = schedule.get("period", "weekly")
    if period == "weekly" and now_local.isoweekday() != int(schedule.get("weekday", 1)):
        return False
    if period == "monthly" and now_local.day != 1:
        return False
    last = schedule.get("last_sent_at")
    if last and now_local - datetime.fromisoformat(last).astimezone(now_local.tzinfo) < timedelta(hours=20):
        return False
    return True


async def send(schedule: dict[str, Any]) -> str:
    async with SessionLocal() as db:
        tz = ZoneInfo(await settings_store.get_setting(db, settings_store.TIMEZONE))
        mail = await config.load(db, config.EMAIL)
        end = datetime.now(tz)
        start = end - timedelta(days=PERIOD_DAYS.get(schedule.get("period", "weekly"), 7))
        fmt = schedule.get("format", "pdf")
        attachments = []
        summary_lines = []
        for kind in schedule.get("kinds") or ["devices"]:
            if kind not in reports.REPORT_KINDS:
                continue
            report = await reports.build(db, kind, start, end, None)
            data = export.render(report, fmt, tz, "zakazani izveštaj")
            attachments.append((f"smartdisk-{kind}-{end:%Y%m%d}.{fmt}", data, export.FORMATS[fmt]))
            summary_lines.append(f"- {report.title}: {len(report.rows)} redova")
        period_label = {"daily": "Dnevni", "weekly": "Nedeljni", "monthly": "Mesečni"}.get(schedule.get("period"), "")
        subject = f"[SmartDisk] {period_label} izveštaj - {schedule.get('name') or ''}".strip()
        body = (f"{period_label} izveštaj za period {start:%d.%m.%Y. %H:%M} - {end:%d.%m.%Y. %H:%M}.\n\n"
                + "\n".join(summary_lines) + "\n\nIzveštaji su u prilogu.\n\n- SmartDisk (automatska poruka)")
        recipients = schedule.get("recipients") or mail.get("recipients") or []
        try:
            await email.send(mail, subject, body, recipients, attachments)
            db.add(NotificationLog(channel="email", target=", ".join(recipients), status="sent",
                                   error_message=f"zakazani izveštaj: {schedule.get('name')}"))
        except email.EmailError as exc:
            db.add(NotificationLog(channel="email", target=", ".join(recipients), status="failed",
                                   error_message=f"zakazani izveštaj: {exc}"))
            await db.commit()
            raise ValueError(str(exc)) from exc
        await db.commit()
    return f"Izveštaj je poslat ({len(attachments)} prilog(a)) na: {', '.join(recipients)}."


async def run_due() -> None:
    async with SessionLocal() as db:
        tz = ZoneInfo(await settings_store.get_setting(db, settings_store.TIMEZONE))
        items = (await config.load_raw(db, KEY) or {}).get("items", [])
    now_local = datetime.now(tz)
    changed = False
    for schedule in items:
        if not due(schedule, now_local):
            continue
        try:
            await send(schedule)
            schedule["last_status"] = "ok"
        except Exception as exc:  # greška jednog rasporeda ne sme da zaustavi ostale
            log.warning("Zakazani izveštaj %s nije poslat: %s", schedule.get("name"), exc)
            schedule["last_status"] = f"greška: {exc}"
        schedule["last_sent_at"] = now_local.isoformat()
        changed = True
    if changed:
        async with SessionLocal() as db:
            await config.save(db, KEY, {"items": items}, "scheduler")
            await db.commit()
