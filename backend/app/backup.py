"""Backup baze (spec. §16.5): pg_dump u custom formatu, provera integriteta (pg_restore --list), rotacija.

Baza sadrži i podešavanja aplikacije i šifrovane kredencijale. Master ključ (/etc/smartdisk/smartdisk.env)
se NE nalazi u backup-u i čuva se odvojeno - bez njega šifrovani SSH ključevi i lozinke nisu upotrebljivi.
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import get_settings
from .models import utcnow

log = logging.getLogger("smartdisk.backup")

BACKUP_DIR = Path(os.environ.get("SMARTDISK_BACKUP_DIR", "/var/lib/smartdisk/backups"))
NAME_RE = re.compile(r"^smartdisk-(\d{8}-\d{6})\.dump$")


class BackupError(Exception):
    pass


def _pg_args() -> list[str]:
    url = urlparse(get_settings().database_url.replace("postgresql+asyncpg", "postgresql"))
    args = []
    host = parse_qs(url.query).get("host", [None])[0] or url.hostname
    if host:
        args += ["-h", host]
    if url.port:
        args += ["-p", str(url.port)]
    if url.username:
        args += ["-U", url.username]
    return args + [url.path.lstrip("/") or "smartdisk"]


async def _run(*cmd: str, timeout: int = 900) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        raise BackupError("Backup nije završen na vreme.") from None
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def verify(path: Path) -> int:
    """Provera integriteta: pg_restore mora da pročita sadržaj arhive. Vraća broj stavki."""
    code, out, err = await _run("pg_restore", "--list", str(path), timeout=300)
    if code != 0:
        raise BackupError(f"Backup {path.name} nije ispravan: {err.strip()[:300]}")
    entries = [line for line in out.splitlines() if line and not line.startswith(";")]
    if not any(" TABLE DATA " in line for line in entries):
        raise BackupError(f"Backup {path.name} ne sadrži podatke tabela.")
    return len(entries)


async def create(keep: int) -> dict[str, Any]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"smartdisk-{stamp}.dump"
    partial = target.with_suffix(".partial")
    started = utcnow()
    try:
        code, _, err = await _run("pg_dump", "-Fc", "--no-owner", "-f", str(partial), *_pg_args())
        if code != 0:
            raise BackupError(f"pg_dump nije uspeo: {err.strip()[:300]}")
        entries = await verify(partial)
        partial.rename(target)
        os.chmod(target, 0o600)
    except (BackupError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise BackupError(str(exc)) from exc
    removed = rotate(keep)
    info = {"file": target.name, "size_bytes": target.stat().st_size, "entries": entries, "started_at": started,
            "finished_at": utcnow(), "status": "ok", "removed": removed}
    log.info("Backup napravljen: %s (%s B, %s stavki)", target.name, info["size_bytes"], entries)
    return info


def rotate(keep: int) -> list[str]:
    files = sorted((p for p in BACKUP_DIR.glob("smartdisk-*.dump") if NAME_RE.match(p.name)), reverse=True)
    removed = []
    for old in files[max(1, keep):]:
        old.unlink(missing_ok=True)
        removed.append(old.name)
    return removed


def list_backups() -> list[dict[str, Any]]:
    if not BACKUP_DIR.exists():
        return []
    out = []
    for p in sorted(BACKUP_DIR.glob("smartdisk-*.dump"), reverse=True):
        m = NAME_RE.match(p.name)
        if not m:
            continue
        st = p.stat()
        out.append({"file": p.name, "size_bytes": st.st_size,
                    "created_at": datetime.strptime(m.group(1), "%Y%m%d-%H%M%S").astimezone()})
    return out
