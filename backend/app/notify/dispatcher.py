"""Slanje obaveštenja o alarmima kroz kanale: Web Push, e-pošta (SMTP) i MQTT (spec. §11.2, §12, §13)."""

import logging
from typing import Any

from sqlalchemy import delete, select

from ..db import SessionLocal
from ..events import Notice
from ..health import SEVERITY_RANK
from ..models import Device, Event, NotificationLog, PushSubscription, utcnow
from datetime import datetime

from . import channels, config, email, mqtt, push

log = logging.getLogger("smartdisk.notify")

SEVERITY_LABEL = {"info": "Informacija", "warning": "Upozorenje", "high": "Visoko", "critical": "Kritično"}
KIND_LABEL = {"opened": "", "escalated": "Pogoršanje – ", "reminder": "Podsetnik – ", "resolved": "Rešeno – "}


def _text(event: Event, kind: str) -> tuple[str, str]:
    title = f"{KIND_LABEL[kind]}{SEVERITY_LABEL[event.severity]}: {event.title}"
    return title, event.message


async def dispatch(notices: list[Notice]) -> None:
    for notice in notices:
        try:
            await _dispatch_one(notice)
        except Exception:
            log.exception("Slanje obaveštenja za alarm %s nije uspelo", notice.event_id)


async def _dispatch_one(notice: Notice) -> None:
    async with SessionLocal() as db:
        event = await db.get(Event, notice.event_id)
        if event is None:
            return
        general = await config.load(db, config.GENERAL)
        if notice.kind == "resolved" and not general.get("notify_resolved", True):
            return
        device = await db.get(Device, event.device_id) if event.device_id else None
        base = (general.get("base_url") or "").rstrip("/")
        url = f"{base}/alarmi/{event.id}" if base else f"/alarmi/{event.id}"
        title, body = _text(event, notice.kind)
        logs: list[NotificationLog] = []

        # MQTT: svaki događaj, bez filtera (Home Assistant automatizacije filtriraju same)
        if mqtt.state.queue is not None:
            mqtt.publish_event({
                "id": event.id, "kind": notice.kind, "severity": event.severity, "status": event.status,
                "category": event.category, "rule": event.rule, "title": event.title, "message": event.message,
                "device": device.name if device else None, "device_id": event.device_id, "disk_id": event.disk_id,
                "pool_id": event.pool_id, "first_seen_at": event.first_seen_at, "last_seen_at": event.last_seen_at,
            })
            mqtt.publish_state()
            logs.append(NotificationLog(event_id=event.id, channel="mqtt", target="events", status="sent"))

        # E-pošta
        # Režim održavanja: ne-kritična obaveštenja se ne šalju (MQTT telemetrija ide i dalje).
        until = general.get("maintenance_until")
        if until and event.severity != "critical" and datetime.fromisoformat(until) > utcnow():
            db.add(NotificationLog(event_id=event.id, channel="all", status="skipped",
                                   error_message=f"Režim održavanja do {until}"))
            if notice.kind != "resolved":
                event.last_notified_at = utcnow()
                event.notified_severity = event.severity
            for entry in logs:
                db.add(entry)
            await db.commit()
            return

        # Telegram, Pushover, webhook
        extra = channels.merged((await config.load_raw(db, channels.CHANNELS)))
        for name, ch in extra.items():
            if not ch.get("enabled") or (SEVERITY_RANK[event.severity] < SEVERITY_RANK[ch.get("min_severity", "high")]
                                         and notice.kind != "resolved"):
                continue
            payload = {"id": event.id, "kind": notice.kind, "severity": event.severity, "status": event.status,
                       "title": event.title, "message": event.message, "device": device.name if device else None,
                       "disk_id": event.disk_id, "pool_id": event.pool_id, "url": url,
                       "first_seen_at": event.first_seen_at, "last_seen_at": event.last_seen_at}
            try:
                await channels.send(name, ch, title, body, url, event.severity, payload)
                logs.append(NotificationLog(event_id=event.id, channel=name, status="sent"))
            except channels.ChannelError as exc:
                logs.append(NotificationLog(event_id=event.id, channel=name, status="failed", error_message=str(exc)))

        mail = await config.load(db, config.EMAIL)
        if mail.get("enabled") and SEVERITY_RANK[event.severity] >= SEVERITY_RANK[mail.get("min_severity", "high")]:
            text = (f"{body}\n\nUređaj: {device.name if device else '—'}\nNivo: {SEVERITY_LABEL[event.severity]}\n"
                    f"Prvi put: {event.first_seen_at:%d.%m.%Y. %H:%M} UTC · ponavljanja: {event.occurrence_count}\n"
                    f"Detalji: {url}\n\n— SmartDisk (automatska poruka)")
            try:
                await email.send(mail, f"[SmartDisk] {title}", text)
                logs.append(NotificationLog(event_id=event.id, channel="email", target=", ".join(mail.get("recipients") or []), status="sent"))
            except email.EmailError as exc:
                logs.append(NotificationLog(event_id=event.id, channel="email", status="failed", error_message=str(exc)))

        # Web Push
        subs = list(await db.scalars(select(PushSubscription)))
        if subs:
            keys = await push.vapid_keys(db)
            subject = f"mailto:{mail['from_addr']}" if mail.get("from_addr") else "mailto:smartdisk@example.invalid"
            payload = {"title": title, "body": body[:400], "url": url, "tag": event.fingerprint,
                       "severity": event.severity, "renotify": notice.kind != "resolved"}
            now = utcnow()
            for sub in subs:
                if sub.muted_until and sub.muted_until > now:
                    continue
                if SEVERITY_RANK[event.severity] < SEVERITY_RANK[sub.min_severity] and notice.kind != "resolved":
                    continue
                if sub.device_ids and event.device_id not in sub.device_ids:
                    continue
                target = (sub.user_agent or "pregledač")[:120]
                try:
                    await push.send({"endpoint": sub.endpoint, "p256dh": sub.p256dh, "auth": sub.auth}, payload,
                                     keys["private_pem"], subject)
                    sub.last_success_at = now
                    sub.last_error = None
                    logs.append(NotificationLog(event_id=event.id, channel="push", target=target, status="sent"))
                except push.PushGone:
                    await db.execute(delete(PushSubscription).where(PushSubscription.id == sub.id))
                    logs.append(NotificationLog(event_id=event.id, channel="push", target=target, status="failed",
                                                error_message="Pretplata više ne važi (uklonjena)."))
                except Exception as exc:
                    sub.last_error = str(exc)[:500]
                    logs.append(NotificationLog(event_id=event.id, channel="push", target=target, status="failed",
                                                error_message=str(exc)[:500]))

        if notice.kind != "resolved":
            event.last_notified_at = utcnow()
            event.notified_severity = event.severity
        for entry in logs:
            db.add(entry)
        await db.commit()


async def send_test(channel: str, cfg: dict[str, Any] | None = None, subscription_id: int | None = None) -> str:
    """Probna poruka (dugme u podešavanjima). Vraća opis rezultata ili podiže ValueError."""
    async with SessionLocal() as db:
        if channel == "email":
            mail = cfg or await config.load(db, config.EMAIL)
            try:
                await email.send(mail, "[SmartDisk] Probna poruka",
                                 "Ovo je probna poruka iz SmartDisk aplikacije. Obaveštenja e-poštom rade.")
            except email.EmailError as exc:
                raise ValueError(str(exc)) from exc
            db.add(NotificationLog(channel="email", target=", ".join(mail.get("recipients") or []), status="sent",
                                   error_message="probna poruka"))
            await db.commit()
            return "Probna poruka je poslata."
        if channel == "push":
            sub = await db.get(PushSubscription, subscription_id)
            if sub is None:
                raise ValueError("Pretplata nije pronađena.")
            keys = await push.vapid_keys(db)
            mail = await config.load(db, config.EMAIL)
            subject = f"mailto:{mail['from_addr']}" if mail.get("from_addr") else "mailto:smartdisk@example.invalid"
            try:
                await push.send({"endpoint": sub.endpoint, "p256dh": sub.p256dh, "auth": sub.auth},
                                {"title": "SmartDisk – probno obaveštenje", "body": "Web Push obaveštenja rade.",
                                 "url": "/alarmi", "tag": "smartdisk-test"}, keys["private_pem"], subject)
            except Exception as exc:
                raise ValueError(f"Slanje nije uspelo: {exc}") from exc
            sub.last_success_at = utcnow()
            db.add(NotificationLog(channel="push", target=(sub.user_agent or "")[:120], status="sent", error_message="probna poruka"))
            await db.commit()
            return "Probno obaveštenje je poslato."
    raise ValueError("Nepoznat kanal.")
