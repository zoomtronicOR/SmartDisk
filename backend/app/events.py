"""Upravljanje alarmima (spec. §8.9, §11.2, §11.3): deduplikacija po fingerprint-u, potvrda uslova,
eskalacija, cooldown, ponovno obaveštavanje i automatsko rešavanje kada uslov prestane.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .health import SEVERITY_RANK, Condition, Evaluation
from .models import Event, EventHistory, utcnow

log = logging.getLogger("smartdisk.events")

# Statusi: pending (čeka potvrdu u narednim procenama, ne prikazuje se), open, acknowledged, resolved.
ACTIVE = ("pending", "open", "acknowledged")


@dataclass
class Notice:
    """Šta treba poslati kanalima obaveštenja posle commit-a."""

    event_id: int
    kind: str  # opened / escalated / reminder / resolved


async def open_fingerprints(db: AsyncSession, device_id: int) -> set[str]:
    rows = await db.scalars(select(Event.fingerprint).where(Event.device_id == device_id, Event.status.in_(("open", "acknowledged"))))
    return set(rows)


def _history(db: AsyncSession, event: Event, action: str, username: str | None = None, comment: str | None = None) -> None:
    db.add(EventHistory(event_id=event.id, action=action, username=username, severity=event.severity, comment=comment))


async def apply(db: AsyncSession, device_id: int, evaluation: Evaluation, th: dict) -> list[Notice]:
    """Usklađuje alarme uređaja sa procenom. Commit radi pozivalac; obaveštenja se šalju posle commit-a."""
    now = utcnow()
    notices: list[Notice] = []
    current = {c.fingerprint: c for c in evaluation.conditions}
    events = list(await db.scalars(
        select(Event).where(Event.device_id == device_id).where(
            (Event.status.in_(ACTIVE)) | (Event.resolved_at >= now - timedelta(minutes=th["cooldown_minutes"]))
        ).order_by(Event.id)
    ))
    active = {e.fingerprint: e for e in events if e.status in ACTIVE}
    recently_resolved = {e.fingerprint: e for e in events if e.status == "resolved"}

    for fp, cond in current.items():
        event = active.get(fp)
        if event is None and fp in recently_resolved:
            # Cooldown: isti problem se vratio ubrzo posle rešavanja → isti alarm se ponovo otvara, bez novog obaveštenja
            # osim ako je ozbiljniji nego što je već bio prijavljen.
            event = recently_resolved[fp]
            event.status = "open"
            event.resolved_at = None
            event.resolved_by = None
            _update(event, cond, now)
            _history(db, event, "reopened")
            if SEVERITY_RANK[cond.severity] > SEVERITY_RANK.get(event.notified_severity or "info", 0):
                notices.append(Notice(event.id, "escalated"))
            continue
        if event is None:
            confirmations = max(1, int(th["confirmations"]))
            event = Event(
                fingerprint=fp, device_id=cond.device_id, disk_id=cond.disk_id, pool_id=cond.pool_id,
                severity=cond.severity, max_severity=cond.severity, category=cond.category, rule=cond.rule,
                title=cond.title[:255], message=cond.message, metric=cond.metric,
                previous_value=cond.previous_value, current_value=cond.current_value, period=cond.period,
                details=cond.details or None, status="pending" if confirmations > 1 else "open",
                first_seen_at=now, last_seen_at=now, occurrence_count=1,
            )
            db.add(event)
            await db.flush()
            if event.status == "open":
                _history(db, event, "opened")
                notices.append(Notice(event.id, "opened"))
            continue

        old_rank = SEVERITY_RANK[event.severity]
        _update(event, cond, now)
        event.occurrence_count += 1
        if event.status == "pending":
            if event.occurrence_count >= max(1, int(th["confirmations"])):
                event.status = "open"
                _history(db, event, "opened")
                notices.append(Notice(event.id, "opened"))
            continue
        new_rank = SEVERITY_RANK[cond.severity]
        if new_rank > old_rank:
            # Pogoršanje: potvrda više ne pokriva novi nivo, alarm ponovo postaje otvoren.
            event.status = "open"
            _history(db, event, "escalated")
            notices.append(Notice(event.id, "escalated"))
        elif new_rank < old_rank:
            _history(db, event, "deescalated")
        elif (event.status == "open" and event.last_notified_at
              and now - event.last_notified_at >= timedelta(hours=th["renotify_hours"])):
            notices.append(Notice(event.id, "reminder"))

    # Rešavanje: samo alarmi čije je pravilo stvarno provereno u ovoj proceni
    for fp, event in active.items():
        if fp in current or event.rule not in evaluation.rules:
            continue
        if event.status == "pending":
            await db.delete(event)
            continue
        event.status = "resolved"
        event.resolved_at = now
        _history(db, event, "resolved", comment="Uslov više nije prisutan (automatski).")
        if event.notified_severity:
            notices.append(Notice(event.id, "resolved"))
    return notices


def _update(event: Event, cond: Condition, now) -> None:  # noqa: ANN001
    event.severity = cond.severity
    if SEVERITY_RANK[cond.severity] > SEVERITY_RANK[event.max_severity]:
        event.max_severity = cond.severity
    event.title = cond.title[:255]
    event.message = cond.message
    if cond.previous_value is not None:
        event.previous_value = cond.previous_value
    event.current_value = cond.current_value
    event.period = cond.period
    event.details = cond.details or None
    event.last_seen_at = now
