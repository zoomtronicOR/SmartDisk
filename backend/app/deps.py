"""Autentifikacija preko sesijskog kolačića, CSRF provera i provera uloga."""

from collections.abc import Awaitable, Callable
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_db
from .models import User, UserSession, utcnow
from .security import hash_token, tokens_equal

SESSION_COOKIE = "sd_session"
CSRF_COOKIE = "sd_csrf"
CSRF_HEADER = "X-CSRF-Token"
# Pozadinsko osvežavanje (polling) ne produžava sesiju, da bi istek zbog neaktivnosti radio.
BACKGROUND_HEADER = "X-Background"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ALLOWED_DURING_PASSWORD_CHANGE = {"/api/me", "/api/auth/logout", "/api/auth/change-password"}


def set_session_cookies(response: Response, token: str, csrf: str) -> None:
    settings = get_settings()
    max_age = settings.session_max_hours * 3600
    common = {"max_age": max_age, "secure": settings.cookie_secure, "samesite": "strict", "path": "/"}
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    settings = get_settings()
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Niste prijavljeni.")

    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_token(token))
        )
    ).first()
    if row is None:
        raise HTTPException(401, "Sesija nije važeća. Prijavite se ponovo.")
    session, user = row

    now = utcnow()
    idle_expired = now - session.last_seen_at > timedelta(minutes=settings.session_idle_minutes)
    if now >= session.expires_at or idle_expired or not user.is_active:
        await db.delete(session)
        await db.commit()
        raise HTTPException(401, "Sesija je istekla. Prijavite se ponovo.")

    if request.method not in SAFE_METHODS:
        if not tokens_equal(request.headers.get(CSRF_HEADER, ""), session.csrf_token):
            raise HTTPException(403, "Neispravan CSRF token. Osvežite stranicu.")

    if user.must_change_password and request.url.path not in ALLOWED_DURING_PASSWORD_CHANGE:
        raise HTTPException(403, "Morate promeniti lozinku pre nastavka rada.")

    if request.headers.get(BACKGROUND_HEADER) != "1" and now - session.last_seen_at > timedelta(seconds=30):
        session.last_seen_at = now
        await db.commit()

    request.state.session_id = session.id
    return user


def require_roles(*roles: str) -> Callable[..., Awaitable[User]]:
    async def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Nemate dozvolu za ovu radnju.")
        return user

    return dependency


admin_only = require_roles("admin")
operator_or_admin = require_roles("admin", "operator")
