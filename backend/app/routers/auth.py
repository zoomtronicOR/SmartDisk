from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit, client_ip
from ..config import get_settings
from ..db import get_db
from ..deps import clear_session_cookies, current_user, set_session_cookies
from ..models import User, UserSession, utcnow
from ..schemas import ChangePasswordIn, LoginIn, UserOut
from ..security import (
    LoginRateLimiter,
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    password_problem,
    verify_password,
)

router = APIRouter(prefix="/api", tags=["auth"])

_settings = get_settings()
login_limiter = LoginRateLimiter(_settings.login_rate_per_ip, _settings.login_rate_window_seconds)


@router.post("/auth/login", response_model=UserOut)
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> User:
    settings = get_settings()
    ip = client_ip(request) or "unknown"
    if not login_limiter.allow(ip):
        raise HTTPException(429, "Previše pokušaja prijave. Pokušajte ponovo za nekoliko minuta.")

    username = body.username.strip().lower()
    user = await db.scalar(select(User).where(User.username == username))
    now = utcnow()

    if user is not None and user.locked_until is not None and user.locked_until > now:
        audit(db, request, user, "login.locked")
        await db.commit()
        raise HTTPException(403, "Nalog je privremeno zaključan zbog više neuspešnih pokušaja prijave.")

    password_ok = verify_password(user.password_hash if user else None, body.password)
    if user is None or not password_ok or not user.is_active:
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                user.failed_login_count = 0
                audit(db, request, user, "user.auto_locked", "user", user.id)
        audit(db, request, user, "login.failure", details={"username": username}, username=username)
        await db.commit()
        raise HTTPException(401, "Pogrešno korisničko ime ili lozinka.")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    token, csrf = new_token(), new_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            csrf_token=csrf,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_max_hours),
            ip=ip,
            user_agent=(request.headers.get("user-agent") or "")[:255],
        )
    )
    audit(db, request, user, "login.success")
    await db.commit()
    login_limiter.reset(ip)
    set_session_cookies(response, token, csrf)
    return user


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request, response: Response, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> None:
    await db.execute(delete(UserSession).where(UserSession.id == request.state.session_id))
    audit(db, request, user, "logout")
    await db.commit()
    clear_session_cookies(response)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/auth/change-password", status_code=204)
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Trenutna lozinka nije ispravna.")
    if body.new_password == body.current_password:
        raise HTTPException(400, "Nova lozinka mora biti drugačija od trenutne.")
    problem = password_problem(body.new_password, user.username)
    if problem:
        raise HTTPException(400, problem)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    # Ostale sesije korisnika se odjavljuju; tekuća ostaje.
    await db.execute(
        delete(UserSession).where(UserSession.user_id == user.id, UserSession.id != request.state.session_id)
    )
    audit(db, request, user, "user.password_changed", "user", user.id)
    await db.commit()
