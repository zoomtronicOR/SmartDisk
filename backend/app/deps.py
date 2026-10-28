"""Autentifikacija preko sesijskog kolačića, CSRF provera i provera uloga."""

from collections.abc import Awaitable, Callable
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_db
from .models import ApiToken, User, UserSession, utcnow
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


TOKEN_PREFIX = "sdk_"
SCOPE_ROLE = {"read": "viewer", "operator": "operator"}


async def _token_user(request: Request, db: AsyncSession, raw: str) -> User:
    """API token (Authorization: Bearer sdk_…): uloga je ograničena dozvolom tokena, nikad administrator."""
    row = (await db.execute(
        select(ApiToken, User).join(User, User.id == ApiToken.user_id).where(ApiToken.token_hash == hash_token(raw))
    )).first()
    now = utcnow()
    if row is None:
        raise HTTPException(401, "API token nije važeći.")
    token, owner = row
    if token.revoked_at is not None or (token.expires_at and token.expires_at <= now) or not owner.is_active:
        raise HTTPException(401, "API token je istekao ili opozvan.")
    if token.scope == "read" and request.method not in SAFE_METHODS:
        raise HTTPException(403, "Token ima samo dozvolu čitanja.")
    if token.last_used_at is None or now - token.last_used_at > timedelta(minutes=1):
        token.last_used_at = now
        token.last_used_ip = request.client.host if request.client else None
        await db.commit()
    role = SCOPE_ROLE[token.scope]
    if owner.role == "viewer":
        role = "viewer"
    request.state.api_token_id = token.id
    # Privremeni objekat (nije u sesiji baze): isti korisnik, ali sa ulogom tokena.
    return User(id=owner.id, username=f"{owner.username} (token „{token.name}”)", role=role, is_active=True,
                must_change_password=False, email=None, password_hash="", failed_login_count=0)


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    settings = get_settings()
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return await _token_user(request, db, auth[7:].strip())
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


async def session_user(request: Request, user: User = Depends(current_user)) -> User:
    """Samo prijavljen korisnik (kolačić), ne API token – za upravljanje tokenima i slično."""
    if getattr(request.state, "api_token_id", None):
        raise HTTPException(403, "Ova radnja nije dozvoljena API tokenom.")
    return user
operator_or_admin = require_roles("admin", "operator")
