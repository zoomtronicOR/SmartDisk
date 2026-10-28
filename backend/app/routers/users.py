from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..db import get_db
from ..deps import admin_only
from ..models import User, UserSession
from ..schemas import PasswordResetIn, UserCreate, UserOut, UserUpdate
from ..security import hash_password, password_problem

router = APIRouter(prefix="/api/users", tags=["users"])


async def _get_user(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Korisnik ne postoji.")
    return user


async def _other_active_admins(db: AsyncSession, user_id: int) -> int:
    return await db.scalar(
        select(func.count()).select_from(User).where(User.role == "admin", User.is_active, User.id != user_id)
    ) or 0


@router.get("", response_model=list[UserOut])
async def list_users(_: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> list[User]:
    return list(await db.scalars(select(User).order_by(User.username)))


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate, request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)
) -> User:
    if await db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "Korisnik sa tim korisničkim imenom već postoji.")
    problem = password_problem(body.password, body.username)
    if problem:
        raise HTTPException(400, problem)
    user = User(
        username=body.username,
        email=body.email or None,
        role=body.role,
        password_hash=hash_password(body.password),
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    audit(db, request, admin, "user.created", "user", user.id, {"username": user.username, "role": user.role})
    await db.commit()
    return user


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    admin: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await _get_user(db, user_id)
    changes: dict[str, object] = {}
    losing_admin = (body.role is not None and body.role != "admin") or body.is_active is False
    if user.role == "admin" and losing_admin and await _other_active_admins(db, user.id) == 0:
        raise HTTPException(400, "Mora postojati bar jedan aktivan administrator.")
    if user.id == admin.id and body.is_active is False:
        raise HTTPException(400, "Ne možete deaktivirati sopstveni nalog.")

    if "email" in body.model_fields_set and body.email != user.email:
        user.email = body.email or None
        changes["email"] = user.email
    if body.role is not None and body.role != user.role:
        changes["role"] = {"from": user.role, "to": body.role}
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = body.is_active
        changes["is_active"] = body.is_active
        if not body.is_active:
            await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    if changes:
        audit(db, request, admin, "user.updated", "user", user.id, changes)
    await db.commit()
    return user


@router.post("/{user_id}/reset-password", status_code=204)
async def reset_password(
    user_id: int,
    body: PasswordResetIn,
    request: Request,
    admin: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await _get_user(db, user_id)
    problem = password_problem(body.new_password, user.username)
    if problem:
        raise HTTPException(400, problem)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    audit(db, request, admin, "user.password_reset", "user", user.id)
    await db.commit()


@router.post("/{user_id}/unlock", status_code=204)
async def unlock_user(
    user_id: int, request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)
) -> None:
    user = await _get_user(db, user_id)
    user.failed_login_count = 0
    user.locked_until = None
    audit(db, request, admin, "user.unlocked", "user", user.id)
    await db.commit()


@router.post("/{user_id}/logout-all", status_code=204)
async def logout_all(
    user_id: int, request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)
) -> None:
    user = await _get_user(db, user_id)
    await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    audit(db, request, admin, "user.sessions_revoked", "user", user.id)
    await db.commit()
