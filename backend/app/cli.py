"""Administrativne komande:

    python -m app.cli create-admin <korisnicko_ime>
    python -m app.cli reset-password <korisnicko_ime>
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import delete, select

from .db import SessionLocal, engine
from .models import AuditLog, User, UserSession
from .security import hash_password, password_problem


def _ask_password(username: str) -> str:
    while True:
        password = getpass.getpass("Lozinka: ")
        problem = password_problem(password, username)
        if problem:
            print(problem)
            continue
        if getpass.getpass("Ponovite lozinku: ") != password:
            print("Lozinke se ne poklapaju.")
            continue
        return password


async def create_admin(username: str) -> int:
    username = username.strip().lower()
    async with SessionLocal() as db:
        if await db.scalar(select(User).where(User.username == username)):
            print(f"Korisnik „{username}” već postoji.")
            return 1
        password = _ask_password(username)
        user = User(username=username, role="admin", password_hash=hash_password(password))
        db.add(user)
        await db.flush()
        db.add(AuditLog(action="user.created", entity_type="user", entity_id=str(user.id),
                        username="cli", details={"username": username, "role": "admin"}))
        await db.commit()
    print(f"Administrator „{username}” je kreiran.")
    return 0


async def reset_password(username: str) -> int:
    username = username.strip().lower()
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username))
        if user is None:
            print(f"Korisnik „{username}” ne postoji.")
            return 1
        user.password_hash = hash_password(_ask_password(username))
        user.failed_login_count = 0
        user.locked_until = None
        user.is_active = True
        await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        db.add(AuditLog(action="user.password_reset", entity_type="user", entity_id=str(user.id), username="cli"))
        await db.commit()
    print(f"Lozinka za „{username}” je promenjena, nalog je otključan.")
    return 0


async def _main(args: argparse.Namespace) -> int:
    try:
        if args.command == "create-admin":
            return await create_admin(args.username)
        return await reset_password(args.username)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="smartdisk")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create-admin", help="Kreira administratora").add_argument("username")
    sub.add_parser("reset-password", help="Postavlja novu lozinku i otključava nalog").add_argument("username")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
