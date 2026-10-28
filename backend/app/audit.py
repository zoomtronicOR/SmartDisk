from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog, User


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def audit(
    db: AsyncSession,
    request: Request | None,
    user: User | None,
    action: str,
    entity_type: str | None = None,
    entity_id: Any = None,
    details: dict[str, Any] | None = None,
    username: str | None = None,
) -> None:
    """Dodaje audit zapis u tekuću transakciju; pozivalac radi commit. Nikad ne upisivati tajne u details."""
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else username,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            source_ip=client_ip(request),
            details=details,
        )
    )
