"""Alarmi (spec. §11.3) i podešavanja obaveštenja (SMTP, MQTT, Web Push, pragovi)."""

import hashlib
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto
from ..audit import audit
from ..db import get_db
from ..deps import admin_only, current_user, operator_or_admin
from ..health import DEFAULT_THRESHOLDS, SEVERITIES, merge_thresholds
from ..models import Device, Disk, Event, EventHistory, NotificationLog, PushSubscription, StoragePool, User, utcnow
from ..notify import config, dispatcher, mqtt, push

router = APIRouter(prefix="/api", tags=["alarms"])


def event_dict(e: Event, names: dict[int, str], disks: dict[int, str], pools: dict[int, str]) -> dict[str, Any]:
    return {
        "id": e.id, "severity": e.severity, "max_severity": e.max_severity, "status": e.status, "category": e.category,
        "rule": e.rule, "title": e.title, "message": e.message, "metric": e.metric,
        "previous_value": e.previous_value, "current_value": e.current_value, "period": e.period, "details": e.details,
        "device_id": e.device_id, "device_name": names.get(e.device_id or 0), "disk_id": e.disk_id,
        "disk_name": disks.get(e.disk_id or 0), "pool_id": e.pool_id, "pool_name": pools.get(e.pool_id or 0),
        "first_seen_at": e.first_seen_at, "last_seen_at": e.last_seen_at, "occurrence_count": e.occurrence_count,
        "acknowledged_by": e.acknowledged_by, "acknowledged_at": e.acknowledged_at, "resolved_at": e.resolved_at,
        "resolved_by": e.resolved_by, "last_notified_at": e.last_notified_at,
    }


async def _labels(db: AsyncSession, events: list[Event]) -> tuple[dict[int, str], dict[int, str], dict[int, str]]:
    dev_ids = {e.device_id for e in events if e.device_id}
    disk_ids = {e.disk_id for e in events if e.disk_id}
    pool_ids = {e.pool_id for e in events if e.pool_id}
    names = {d.id: d.name for d in await db.scalars(select(Device).where(Device.id.in_(dev_ids)))} if dev_ids else {}
    disks = {d.id: f"{d.device_path} · {d.model or '?'}" for d in await db.scalars(select(Disk).where(Disk.id.in_(disk_ids)))} if disk_ids else {}
    pools = {p.id: p.name for p in await db.scalars(select(StoragePool).where(StoragePool.id.in_(pool_ids)))} if pool_ids else {}
    return names, disks, pools


@router.get("/alarms")
async def list_alarms(
    status: str = "active",  # active (open+acknowledged) / open / acknowledged / resolved / all
    severity: str | None = None,
    device_id: int | None = None,
    disk_id: int | None = None,
    pool_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = select(Event).where(Event.status != "pending")
    if status == "active":
        query = query.where(Event.status.in_(("open", "acknowledged")))
    elif status in ("open", "acknowledged", "resolved"):
        query = query.where(Event.status == status)
    if severity in SEVERITIES:
        query = query.where(Event.severity == severity)
    for col, value in ((Event.device_id, device_id), (Event.disk_id, disk_id), (Event.pool_id, pool_id)):
        if value is not None:
            query = query.where(col == value)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rank = func.array_position(list(reversed(SEVERITIES)), Event.severity)
    rows = list(await db.scalars(query.order_by(Event.status == "resolved", rank, Event.last_seen_at.desc()).limit(limit).offset(offset)))
    labels = await _labels(db, rows)
    return {"items": [event_dict(e, *labels) for e in rows], "total": total}


@router.get("/alarms/summary")
async def alarm_summary(_: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await db.execute(
        select(Event.severity, Event.status, func.count()).where(Event.status.in_(("open", "acknowledged")))
        .group_by(Event.severity, Event.status)
    )).all()
    by_sev = {s: 0 for s in SEVERITIES}
    unack = {s: 0 for s in SEVERITIES}
    for sev, st, n in rows:
        by_sev[sev] += n
        if st == "open":
            unack[sev] += n
    week = utcnow() - timedelta(days=7)
    day = func.date_trunc("day", Event.first_seen_at).label("day")
    per_day = (await db.execute(
        select(day, Event.severity, func.count())
        .where(Event.first_seen_at >= week - timedelta(days=23), Event.status != "pending")
        .group_by(day, Event.severity).order_by(day)
    )).all()
    return {"active": by_sev, "unacknowledged": unack, "total_active": sum(by_sev.values()),
            "per_day": [{"day": d, "severity": s, "count": n} for d, s, n in per_day]}


@router.get("/alarms/{event_id}")
async def get_alarm(event_id: int, _: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    event = await db.get(Event, event_id)
    if event is None or event.status == "pending":
        raise HTTPException(404, "Alarm nije pronađen.")
    data = event_dict(event, *await _labels(db, [event]))
    history = await db.scalars(select(EventHistory).where(EventHistory.event_id == event_id).order_by(EventHistory.created_at))
    data["history"] = [{"created_at": h.created_at, "action": h.action, "username": h.username, "severity": h.severity,
                        "comment": h.comment} for h in history]
    notes = await db.scalars(select(NotificationLog).where(NotificationLog.event_id == event_id).order_by(NotificationLog.sent_at.desc()).limit(50))
    data["notifications"] = [{"channel": n.channel, "target": n.target, "sent_at": n.sent_at, "status": n.status,
                              "error_message": n.error_message} for n in notes]
    return data


class AlarmAction(BaseModel):
    comment: str | None = Field(None, max_length=2000)


@router.post("/alarms/{event_id}/acknowledge")
async def acknowledge(event_id: int, body: AlarmAction, request: Request, user: User = Depends(operator_or_admin),
                      db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Potvrda znači „video sam”, ne „rešeno” - alarm ostaje aktivan dok uslov traje (spec. §11.3)."""
    event = await db.get(Event, event_id)
    if event is None or event.status not in ("open",):
        raise HTTPException(409, "Može se potvrditi samo otvoren alarm.")
    event.status = "acknowledged"
    event.acknowledged_by = user.username
    event.acknowledged_at = utcnow()
    db.add(EventHistory(event_id=event.id, action="acknowledged", username=user.username, severity=event.severity,
                        comment=body.comment))
    audit(db, request, user, "alarm.acknowledged", "event", str(event.id), {"title": event.title})
    await db.commit()
    return {"status": "acknowledged"}


@router.post("/alarms/{event_id}/comment")
async def comment(event_id: int, body: AlarmAction, user: User = Depends(operator_or_admin),
                  db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    event = await db.get(Event, event_id)
    if event is None or event.status == "pending":
        raise HTTPException(404, "Alarm nije pronađen.")
    if not body.comment or not body.comment.strip():
        raise HTTPException(422, "Komentar je prazan.")
    db.add(EventHistory(event_id=event.id, action="comment", username=user.username, comment=body.comment.strip()))
    await db.commit()
    return {"status": "ok"}


@router.post("/alarms/{event_id}/resolve")
async def resolve(event_id: int, body: AlarmAction, request: Request, user: User = Depends(operator_or_admin),
                  db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Ručno zatvaranje. Ako uslov i dalje postoji, sledeći ciklus ga ponovo otvara (posle cooldown-a kao isti alarm)."""
    event = await db.get(Event, event_id)
    if event is None or event.status not in ("open", "acknowledged"):
        raise HTTPException(409, "Alarm nije aktivan.")
    event.status = "resolved"
    event.resolved_at = utcnow()
    event.resolved_by = user.username
    db.add(EventHistory(event_id=event.id, action="resolved", username=user.username, severity=event.severity,
                        comment=body.comment or "Ručno zatvoren."))
    audit(db, request, user, "alarm.resolved", "event", str(event.id), {"title": event.title})
    await db.commit()
    return {"status": "resolved"}


# --- Podešavanja obaveštenja ---


class EmailSettingsIn(BaseModel):
    enabled: bool = False
    host: str = Field("", max_length=253)
    port: int = Field(587, ge=1, le=65535)
    security: str = "starttls"
    username: str = Field("", max_length=255)
    password: str | None = Field(None, max_length=500)  # None = ne menja; "" = briše
    from_addr: str = Field("", max_length=255)
    recipients: list[str] = Field(default_factory=list, max_length=20)
    min_severity: str = "high"

    @field_validator("security")
    @classmethod
    def check_security(cls, v: str) -> str:
        if v not in ("starttls", "ssl", "none"):
            raise ValueError("Bezbednost veze mora biti STARTTLS, SSL ili bez šifrovanja.")
        return v

    @field_validator("min_severity")
    @classmethod
    def check_severity(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError("Nepoznat nivo ozbiljnosti.")
        return v

    @field_validator("recipients")
    @classmethod
    def check_recipients(cls, v: list[str]) -> list[str]:
        out = [r.strip() for r in v if r.strip()]
        for r in out:
            if "@" not in r or " " in r or len(r) > 254:
                raise ValueError(f"Neispravna e-adresa: {r}")
        return out

    @field_validator("from_addr")
    @classmethod
    def check_from(cls, v: str) -> str:
        v = v.strip()
        if v and ("@" not in v or " " in v):
            raise ValueError("Neispravna adresa pošiljaoca.")
        return v


class MqttSettingsIn(BaseModel):
    enabled: bool = False
    host: str = Field("", max_length=253)
    port: int = Field(1883, ge=1, le=65535)
    tls: bool = False
    tls_insecure: bool = False
    username: str = Field("", max_length=255)
    password: str | None = Field(None, max_length=500)
    client_id: str = Field("smartdisk", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    prefix: str = Field("diskmonitor", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_/-]+$")
    qos: int = Field(1, ge=0, le=2)
    retain: bool = True
    heartbeat_seconds: int = Field(60, ge=10, le=3600)
    discovery: bool = True
    discovery_prefix: str = Field("homeassistant", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_/-]+$")
    entities: list[str] = Field(default_factory=lambda: list(config.DEFAULTS[config.MQTT]["entities"]))


class GeneralNotifyIn(BaseModel):
    base_url: str = Field("", max_length=255, pattern=r"^(https?://[^\s/]+)?$")
    notify_resolved: bool = True


def _merge_secret(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    pwd = new.pop("password", None)
    if pwd is None:
        new["password_enc"] = old.get("password_enc")
    elif pwd == "":
        new["password_enc"] = None
    else:
        new["password_enc"] = crypto.encrypt(pwd)
    return new


@router.get("/thresholds")
async def current_thresholds(_: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Pragovi alarma za prikaz (merači, zone) - dostupno svim ulogama, bez podešavanja kanala."""
    return await config.thresholds(db)


@router.get("/notifications/settings")
async def notification_settings(_: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {
        "email": config.public(await config.load(db, config.EMAIL)),
        "mqtt": {**config.public(await config.load(db, config.MQTT)), "status": mqtt.status()},
        "general": await config.load(db, config.GENERAL),
        "thresholds": await config.thresholds(db),
        "threshold_defaults": DEFAULT_THRESHOLDS,
        "mqtt_entities": config.DEFAULTS[config.MQTT]["entities"],
    }


@router.put("/notifications/email")
async def put_email(body: EmailSettingsIn, request: Request, admin: User = Depends(admin_only),
                    db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    old = await config.load(db, config.EMAIL)
    data = _merge_secret(old, body.model_dump())
    data["timeout"] = old.get("timeout", 20)
    if data["enabled"] and (not data["host"] or not data["from_addr"] or not data["recipients"]):
        raise HTTPException(422, "Za uključivanje su obavezni SMTP server, adresa pošiljaoca i bar jedan primalac.")
    await config.save(db, config.EMAIL, data, admin.username)
    audit(db, request, admin, "settings.email_updated", "settings", "email",
          {"enabled": data["enabled"], "host": data["host"], "recipients": len(data["recipients"])})
    await db.commit()
    return config.public(data)


@router.post("/notifications/email/test")
async def test_email(body: EmailSettingsIn, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Probna poruka sa unetim (još nesačuvanim) podešavanjima; prazna lozinka znači „sačuvana”."""
    old = await config.load(db, config.EMAIL)
    cfg = _merge_secret(old, body.model_dump())
    cfg["timeout"] = 20
    try:
        return {"message": await dispatcher.send_test("email", cfg)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put("/notifications/mqtt")
async def put_mqtt(body: MqttSettingsIn, request: Request, admin: User = Depends(admin_only),
                   db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    old = await config.load(db, config.MQTT)
    data = _merge_secret(old, body.model_dump())
    data["entities"] = [e for e in data["entities"] if e in config.DEFAULTS[config.MQTT]["entities"]]
    if data["enabled"] and not data["host"]:
        raise HTTPException(422, "Za uključivanje MQTT-a je obavezna adresa brokera.")
    await config.save(db, config.MQTT, data, admin.username)
    audit(db, request, admin, "settings.mqtt_updated", "settings", "mqtt",
          {"enabled": data["enabled"], "host": data["host"], "prefix": data["prefix"]})
    await db.commit()
    await mqtt.restart()
    return {**config.public(data), "status": mqtt.status()}


@router.post("/notifications/mqtt/test")
async def test_mqtt(body: MqttSettingsIn, _: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    old = await config.load(db, config.MQTT)
    cfg = _merge_secret(old, body.model_dump())
    if not cfg["host"]:
        raise HTTPException(422, "Unesite adresu brokera.")
    try:
        await mqtt.test_connection(cfg)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"message": "Veza sa brokerom i prijava su uspešni."}


@router.put("/notifications/general")
async def put_general(body: GeneralNotifyIn, request: Request, admin: User = Depends(admin_only),
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    data = {**await config.load(db, config.GENERAL), **body.model_dump()}  # režim održavanja ostaje
    await config.save(db, config.GENERAL, data, admin.username)
    audit(db, request, admin, "settings.notify_general_updated", "settings", "notify", data)
    await db.commit()
    return data


@router.put("/notifications/thresholds")
async def put_thresholds(body: dict[str, Any], request: Request, admin: User = Depends(admin_only),
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    merged = merge_thresholds(body)
    problems = _check_thresholds(merged)
    if problems:
        raise HTTPException(422, " ".join(problems))
    old = await config.thresholds(db)
    await config.save(db, config.THRESHOLDS, merged, admin.username)
    changes = {k: {"from": old.get(k), "to": v} for k, v in merged.items() if old.get(k) != v}
    audit(db, request, admin, "settings.thresholds_updated", "settings", "thresholds", changes)
    await db.commit()
    return merged


def _check_thresholds(th: dict[str, Any]) -> list[str]:
    problems = []
    for kind, lim in th["temperature"].items():
        if not all(isinstance(lim[k], (int, float)) for k in ("info", "warning", "critical")) or not (0 < lim["info"] <= lim["warning"] < lim["critical"] <= 120):
            problems.append(f"Temperaturni pragovi za {kind.upper()} moraju biti rastući (informativno ≤ upozorenje < kritično ≤ 120 °C).")
    for key in ("percentage_used", "pool_usage"):
        lim = th[key]
        if not (0 < lim["warning"] <= lim["high"] <= lim["critical"] <= 100):
            problems.append(f"Pragovi „{key}” moraju biti rastući i do 100 %.")
    if not (0 < th["ssd_life_left"]["high"] <= th["ssd_life_left"]["warning"] <= 100):
        problems.append("Pragovi preostalog veka SSD-a: visoko ≤ upozorenje.")
    for key in ("reallocated_high_24h", "reallocated_high_7d", "reallocated_high_30d", "pending_high_24h",
                "uncorrectable_critical_24h", "crc_warning_24h", "temperature_repeat_count", "unreachable_runs",
                "partial_runs", "no_data_runs", "confirmations"):
        if not isinstance(th[key], int) or not 1 <= th[key] <= 10_000:
            problems.append(f"„{key}” mora biti ceo broj od 1 naviše.")
    for key, lo, hi in (("temperature_hysteresis", 0, 20), ("temperature_jump", 1, 60), ("available_spare_min", 0, 100),
                        ("cooldown_minutes", 0, 10_080), ("renotify_hours", 1, 720)):
        if not isinstance(th[key], (int, float)) or not lo <= th[key] <= hi:
            problems.append(f"„{key}” mora biti između {lo} i {hi}.")
    return problems


# --- Web Push ---


@router.get("/notifications/push/vapid")
async def vapid_public(_: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    keys = await push.vapid_keys(db)
    await db.commit()
    return {"public_key": keys["public"]}


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(..., max_length=2000, pattern=r"^https://")
    p256dh: str = Field(..., max_length=255)
    auth: str = Field(..., max_length=255)
    min_severity: str = "warning"
    device_ids: list[int] | None = None
    muted_until: datetime | None = None

    @field_validator("min_severity")
    @classmethod
    def check_severity(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError("Nepoznat nivo ozbiljnosti.")
        return v


def _sub_dict(s: PushSubscription) -> dict[str, Any]:
    return {"id": s.id, "endpoint_host": s.endpoint.split("/")[2] if "//" in s.endpoint else "",
            # Pregledač prepoznaje svoju pretplatu po hešu adrese (sama adresa se ne vraća).
            "endpoint_hash": hashlib.sha256(s.endpoint.encode()).hexdigest(), "user_agent": s.user_agent,
            "min_severity": s.min_severity, "device_ids": s.device_ids, "muted_until": s.muted_until,
            "created_at": s.created_at, "last_success_at": s.last_success_at, "last_error": s.last_error}


@router.get("/notifications/push/subscriptions")
async def my_subscriptions(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return [_sub_dict(s) for s in await db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id))]


@router.post("/notifications/push/subscriptions")
async def subscribe(body: PushSubscriptionIn, request: Request, user: User = Depends(current_user),
                    db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    sub = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=body.endpoint, user_id=user.id, p256dh=body.p256dh, auth=body.auth)
        db.add(sub)
    sub.user_id = user.id
    sub.p256dh, sub.auth = body.p256dh, body.auth
    sub.min_severity = body.min_severity
    sub.device_ids = body.device_ids or None
    sub.muted_until = body.muted_until
    sub.user_agent = (request.headers.get("user-agent") or "")[:255]
    audit(db, request, user, "push.subscribed", "push", None, {"min_severity": body.min_severity})
    await db.commit()
    return _sub_dict(sub)


@router.delete("/notifications/push/subscriptions/{sub_id}")
async def unsubscribe(sub_id: int, request: Request, user: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    sub = await db.get(PushSubscription, sub_id)
    if sub is None or (sub.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Pretplata nije pronađena.")
    await db.delete(sub)
    audit(db, request, user, "push.unsubscribed", "push", str(sub_id), None)
    await db.commit()
    return {"status": "deleted"}


@router.post("/notifications/push/subscriptions/{sub_id}/test")
async def test_push(sub_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    sub = await db.get(PushSubscription, sub_id)
    if sub is None or sub.user_id != user.id:
        raise HTTPException(404, "Pretplata nije pronađena.")
    try:
        return {"message": await dispatcher.send_test("push", subscription_id=sub_id)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/notifications/log")
async def notification_log(limit: int = Query(100, ge=1, le=500), _: User = Depends(admin_only),
                           db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    rows = await db.scalars(select(NotificationLog).order_by(NotificationLog.sent_at.desc()).limit(limit))
    return [{"id": n.id, "event_id": n.event_id, "channel": n.channel, "target": n.target, "sent_at": n.sent_at,
             "status": n.status, "error_message": n.error_message} for n in rows]
