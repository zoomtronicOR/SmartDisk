"""Logo kompanije (prikaz u meniju). Čuva se u bazi, pa ulazi i u backup."""

import base64
import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..db import get_db
from ..deps import admin_only
from ..models import User, utcnow
from ..notify import config

router = APIRouter(prefix="/api/branding", tags=["branding"])

KEY = "branding"
MAX_BYTES = 512 * 1024
# Samo rasterski formati: SVG može da sadrži skripte, pa se ne prihvata.
SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}


def _detect(data: bytes) -> str | None:
    for magic, mime in SIGNATURES.items():
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _load(db: AsyncSession) -> dict[str, Any]:
    return await config.load_raw(db, KEY) or {}


@router.get("")
async def branding_info(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Javno (i stranica za prijavu prikazuje logo): da li logo postoji i oznaka verzije za keš."""
    data = await _load(db)
    return {"has_logo": bool(data.get("logo")), "version": data.get("hash"), "company_name": data.get("company_name") or ""}


@router.get("/logo")
async def logo(db: AsyncSession = Depends(get_db)) -> Response:
    data = await _load(db)
    if not data.get("logo"):
        raise HTTPException(404, "Logo nije postavljen.")
    return Response(
        base64.b64decode(data["logo"]),
        media_type=data["mime"],
        headers={"Cache-Control": "public, max-age=86400", "Content-Security-Policy": "default-src 'none'"},
    )


class LogoIn(BaseModel):
    data_base64: str | None = Field(None, max_length=MAX_BYTES * 2)  # None = samo izmena naziva
    company_name: str = Field("", max_length=100)


@router.put("")
async def put_branding(body: LogoIn, request: Request, admin: User = Depends(admin_only),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    current = await _load(db)
    current["company_name"] = body.company_name.strip()
    if body.data_base64:
        raw = body.data_base64.split(",", 1)[-1]  # prihvata i „data:image/png;base64,…”
        try:
            data = base64.b64decode(raw, validate=True)
        except ValueError as exc:
            raise HTTPException(422, "Fajl nije ispravno poslat.") from exc
        if len(data) > MAX_BYTES:
            raise HTTPException(422, f"Logo je veći od {MAX_BYTES // 1024} KB. Smanjite sliku.")
        mime = _detect(data)
        if mime is None:
            raise HTTPException(422, "Dozvoljeni formati su PNG, JPEG i WebP.")
        current.update(logo=base64.b64encode(data).decode(), mime=mime, size=len(data),
                       hash=hashlib.sha256(data).hexdigest()[:12], updated_at=utcnow().isoformat())
    await config.save(db, KEY, current, admin.username)
    audit(db, request, admin, "settings.branding_updated", "settings", "branding",
          {"logo_changed": bool(body.data_base64), "size": current.get("size"), "company_name": current["company_name"]})
    await db.commit()
    return {"has_logo": bool(current.get("logo")), "version": current.get("hash"), "company_name": current["company_name"]}


@router.delete("/logo")
async def delete_logo(request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    current = await _load(db)
    for key in ("logo", "mime", "size", "hash", "updated_at"):
        current.pop(key, None)
    await config.save(db, KEY, current, admin.username)
    audit(db, request, admin, "settings.branding_logo_removed", "settings", "branding", None)
    await db.commit()
    return {"has_logo": False, "version": None, "company_name": current.get("company_name") or ""}
