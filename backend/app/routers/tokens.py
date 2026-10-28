"""API tokeni (spec. §16.7): pravljenje (token se prikazuje samo jednom), lista, opoziv."""

import secrets
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..db import get_db
from ..deps import TOKEN_PREFIX, session_user
from ..models import ApiToken, User, utcnow
from ..security import hash_token

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


class TokenIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scope: str = Field("read", pattern=r"^(read|operator)$")
    expires_days: int | None = Field(90, ge=1, le=3650)  # None = bez isteka (ne preporučuje se)


def _out(t: ApiToken, owner: str | None = None) -> dict[str, Any]:
    now = utcnow()
    state = "revoked" if t.revoked_at else "expired" if t.expires_at and t.expires_at <= now else "active"
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "scope": t.scope, "created_at": t.created_at,
            "expires_at": t.expires_at, "revoked_at": t.revoked_at, "last_used_at": t.last_used_at,
            "last_used_ip": t.last_used_ip, "state": state, "owner": owner}


@router.get("")
async def list_tokens(user: User = Depends(session_user), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Administrator vidi sve tokene, ostali samo svoje."""
    query = select(ApiToken, User.username).join(User, User.id == ApiToken.user_id).order_by(ApiToken.created_at.desc())
    if user.role != "admin":
        query = query.where(ApiToken.user_id == user.id)
    return [_out(t, owner) for t, owner in (await db.execute(query)).all()]


@router.post("", status_code=201)
async def create_token(body: TokenIn, request: Request, user: User = Depends(session_user),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if body.scope == "operator" and user.role not in ("admin", "operator"):
        raise HTTPException(403, "Korisnik sa ulogom „Pregled” može da napravi samo token za čitanje.")
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ApiToken(user_id=user.id, name=body.name.strip(), token_hash=hash_token(raw), prefix=raw[:10],
                     scope=body.scope, expires_at=utcnow() + timedelta(days=body.expires_days) if body.expires_days else None)
    db.add(token)
    await db.flush()
    audit(db, request, user, "token.created", "api_token", str(token.id),
          {"name": token.name, "scope": token.scope, "expires_days": body.expires_days})
    await db.commit()
    return {**_out(token, user.username), "token": raw}


@router.post("/{token_id}/revoke")
async def revoke_token(token_id: int, request: Request, user: User = Depends(session_user),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    token = await db.get(ApiToken, token_id)
    if token is None or (token.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Token nije pronađen.")
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        audit(db, request, user, "token.revoked", "api_token", str(token.id), {"name": token.name})
        await db.commit()
    return _out(token)


