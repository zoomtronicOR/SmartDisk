import asyncio

import asyncssh
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import collector, crypto, scheduler, settings_store
from ..audit import audit
from ..constants import PLATFORMS
from ..db import get_db
from ..deps import admin_only, current_user, operator_or_admin, session_user
from ..models import CollectionRun, Device, Event, EventHistory, User, utcnow
from ..schemas import (
    CapabilityOut,
    CredentialsIn,
    DeviceCreate,
    DeviceDetailOut,
    DeviceOut,
    DeviceUpdate,
    GeneratedKeyOut,
    HostKeyConfirmIn,
    HostKeyOut,
    RunOut,
    TestResultOut,
)
from ..security import verify_password
from ..ssh.client import SSHError, fetch_host_key, load_private_key

router = APIRouter(prefix="/api/devices", tags=["devices"])

# Reference na pozadinske zadatke, da ih garbage collector ne prekine.
_background: set[asyncio.Task] = set()


def device_status(device: Device) -> str:
    if not collector.is_ready(device):
        return "not_configured"
    if not device.enabled:
        return "disabled"
    if device.last_failure_at and (device.last_success_at is None or device.last_failure_at > device.last_success_at):
        return "error"
    if device.last_success_at:
        return "ok"
    return "waiting"


def to_out(device: Device, default_interval: int) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        name=device.name,
        platform=device.platform,
        platform_label=PLATFORMS.get(device.platform, device.platform),
        host=device.host,
        ssh_port=device.ssh_port,
        ssh_username=device.ssh_username,
        auth_method=device.auth_method,
        has_credentials=bool(device.encrypted_private_key),
        public_key=device.public_key,
        host_key_fingerprint=device.host_key_fingerprint,
        host_key_confirmed_at=device.host_key_confirmed_at,
        host_key_confirmed_by=device.host_key_confirmed_by,
        has_pending_host_key=bool(device.pending_host_key),
        timezone=device.timezone,
        enabled=device.enabled,
        collection_interval_minutes=device.collection_interval_minutes,
        effective_interval_minutes=device.collection_interval_minutes or default_interval,
        connect_timeout=device.connect_timeout,
        command_timeout=device.command_timeout,
        tags=device.tags or [],
        location=device.location,
        note=device.note,
        os_info=device.os_info,
        created_at=device.created_at,
        updated_at=device.updated_at,
        last_seen_at=device.last_seen_at,
        last_success_at=device.last_success_at,
        last_failure_at=device.last_failure_at,
        last_error=device.last_error,
        next_run_at=scheduler.next_run_at(device.id),
        running=collector.is_running(device.id),
        status=device_status(device),  # type: ignore[arg-type]
    )


async def _get_device(db: AsyncSession, device_id: int) -> Device:
    device = await db.get(Device, device_id)
    if device is None or device.deleted_at is not None:
        raise HTTPException(404, "Uređaj ne postoji.")
    return device


async def _ensure_unique_name(db: AsyncSession, name: str, exclude_id: int | None = None) -> None:
    query = select(Device.id).where(func.lower(Device.name) == name.lower(), Device.deleted_at.is_(None))
    if exclude_id is not None:
        query = query.where(Device.id != exclude_id)
    if await db.scalar(query):
        raise HTTPException(409, "Uređaj sa tim nazivom već postoji.")


async def _default_interval(db: AsyncSession) -> int:
    return await settings_store.get_setting(db, settings_store.DEFAULT_INTERVAL)


async def _resync(db: AsyncSession, device: Device) -> None:
    scheduler.sync_device(device, await _default_interval(db))


def _run_out(run: CollectionRun, device_name: str | None = None) -> RunOut:
    out = RunOut.model_validate(run)
    out.device_name = device_name
    return out


@router.get("", response_model=list[DeviceOut])
async def list_devices(_: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[DeviceOut]:
    default_interval = await _default_interval(db)
    devices = await db.scalars(select(Device).where(Device.deleted_at.is_(None)).order_by(Device.name))
    return [to_out(d, default_interval) for d in devices]


@router.post("", response_model=DeviceOut, status_code=201)
async def create_device(
    body: DeviceCreate, request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)
) -> DeviceOut:
    await _ensure_unique_name(db, body.name)
    device = Device(**body.model_dump(), auth_method="key", enabled=False)
    db.add(device)
    await db.flush()
    audit(db, request, admin, "device.created", "device", device.id,
          {"name": device.name, "platform": device.platform, "host": device.host})
    await db.commit()
    await db.refresh(device)
    return to_out(device, await _default_interval(db))


@router.get("/{device_id}", response_model=DeviceDetailOut)
async def get_device(
    device_id: int, _: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> DeviceDetailOut:
    device = await _get_device(db, device_id)
    runs = await db.scalars(
        select(CollectionRun).where(CollectionRun.device_id == device_id)
        .order_by(CollectionRun.started_at.desc()).limit(10)
    )
    caps = await collector.capabilities_for(device_id)
    base = to_out(device, await _default_interval(db))
    return DeviceDetailOut(
        **base.model_dump(),
        capabilities=[CapabilityOut.model_validate(c) for c in caps],
        last_runs=[_run_out(r, device.name) for r in runs],
    )


@router.put("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    body: DeviceUpdate,
    request: Request,
    admin: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> DeviceOut:
    device = await _get_device(db, device_id)
    data = body.model_dump(exclude_unset=True)
    enable = data.pop("enabled", None)
    if "name" in data:
        await _ensure_unique_name(db, data["name"], device.id)
    for nullable_only in ("platform", "host", "ssh_port", "ssh_username", "timezone", "connect_timeout",
                          "command_timeout", "tags"):
        if nullable_only in data and data[nullable_only] is None:
            data.pop(nullable_only)

    changes: dict[str, object] = {}
    for key, value in data.items():
        if getattr(device, key) != value:
            changes[key] = value
            setattr(device, key, value)

    # Promena adrese ili porta znači drugi SSH server: host ključ mora ponovo da se potvrdi.
    if "host" in changes or "ssh_port" in changes:
        device.host_key = None
        device.host_key_fingerprint = None
        device.host_key_confirmed_at = None
        device.host_key_confirmed_by = None
        device.pending_host_key = None
        device.enabled = False
        changes["host_key_reset"] = True

    if enable is not None and enable != device.enabled:
        if enable and not collector.is_ready(device):
            raise HTTPException(400, "Nadzor može da se uključi tek kada uređaj ima SSH ključ i potvrđen host ključ.")
        device.enabled = enable
        changes["enabled"] = enable

    if changes:
        audit(db, request, admin, "device.updated", "device", device.id, changes)
    await db.commit()
    await db.refresh(device)
    await _resync(db, device)
    return to_out(device, await _default_interval(db))


class DeleteAllIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@router.post("/delete-all")
async def delete_all_devices(
    body: DeleteAllIn,
    request: Request,
    admin: User = Depends(admin_only),
    _: User = Depends(session_user),  # samo prijavljen administrator, ne API token
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Uklanja sve uređaje (npr. posle premeštanja kontejnera u drugu mrežu). Potvrda lozinkom administratora.

    Soft-delete kao kod pojedinačnog brisanja: istorija diskova ostaje. Privatni ključevi obrisanih uređaja
    se brišu, a njihovi aktivni alarmi se zatvaraju, jer se uređaji više ne kontaktiraju.
    """
    admin_name = admin.username
    if not verify_password(admin.password_hash, body.password):
        audit(db, request, admin, "device.delete_all_denied", "device", None, {"reason": "pogrešna lozinka"})
        await db.commit()
        raise HTTPException(403, "Lozinka nije ispravna. Uređaji nisu obrisani.")

    devices = list(await db.scalars(select(Device).where(Device.deleted_at.is_(None))))
    now = utcnow()
    names = [d.name for d in devices]
    ids = [d.id for d in devices]
    for device in devices:
        device.deleted_at = now
        device.enabled = False
        device.encrypted_private_key = None
        device.encrypted_passphrase = None
    resolved = 0
    if ids:
        events = await db.scalars(select(Event).where(Event.device_id.in_(ids), Event.status.in_(("open", "acknowledged"))))
        for event in events:
            event.status = "resolved"
            event.resolved_at = now
            event.resolved_by = admin_name
            db.add(EventHistory(event_id=event.id, action="resolved", username=admin_name, severity=event.severity,
                                comment="Zatvoren jer su obrisani svi uređaji."))
            resolved += 1
    audit(db, request, admin, "device.deleted_all", "device", None,
          {"count": len(ids), "devices": names, "alarms_resolved": resolved})
    await db.commit()
    default_interval = await _default_interval(db)
    for device in devices:
        scheduler.sync_device(device, default_interval)
    return {"deleted": len(ids), "alarms_resolved": resolved}


@router.delete("/{device_id}", status_code=204)
async def delete_device(
    device_id: int, request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)
) -> None:
    """Soft-delete: istorijski podaci ostaju u bazi, uređaj se više ne prikazuje i ne kontaktira."""
    device = await _get_device(db, device_id)
    device.deleted_at = utcnow()
    device.enabled = False
    audit(db, request, admin, "device.deleted", "device", device.id, {"name": device.name})
    await db.commit()
    await _resync(db, device)


@router.post("/{device_id}/credentials", response_model=DeviceOut)
async def set_credentials(
    device_id: int,
    body: CredentialsIn,
    request: Request,
    admin: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> DeviceOut:
    device = await _get_device(db, device_id)
    private_key = body.private_key.strip() + "\n"
    try:
        key = load_private_key(private_key, body.passphrase)
    except SSHError as exc:
        raise HTTPException(400, exc.message) from exc
    device.encrypted_private_key = crypto.encrypt(private_key)
    device.encrypted_passphrase = crypto.encrypt(body.passphrase) if body.passphrase else None
    device.public_key = key.export_public_key().decode().strip()
    audit(db, request, admin, "device.credentials_set", "device", device.id, {"source": "uploaded"})
    await db.commit()
    await db.refresh(device)
    return to_out(device, await _default_interval(db))


@router.post("/{device_id}/generate-key", response_model=GeneratedKeyOut)
async def generate_key(
    device_id: int, request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)
) -> GeneratedKeyOut:
    device = await _get_device(db, device_id)
    key = asyncssh.generate_private_key("ssh-ed25519", comment=f"smartdisk-{device.id}")
    device.encrypted_private_key = crypto.encrypt(key.export_private_key().decode())
    device.encrypted_passphrase = None
    device.public_key = key.export_public_key().decode().strip()
    audit(db, request, admin, "device.credentials_set", "device", device.id, {"source": "generated"})
    await db.commit()
    return GeneratedKeyOut(public_key=device.public_key)


@router.post("/{device_id}/host-key/fetch", response_model=HostKeyOut)
async def fetch_device_host_key(
    device_id: int, request: Request, admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)
) -> HostKeyOut:
    device = await _get_device(db, device_id)
    try:
        key = await fetch_host_key(device.host, device.ssh_port, device.connect_timeout)
    except SSHError as exc:
        raise HTTPException(502, exc.message) from exc
    device.pending_host_key = key.export_public_key().decode().strip()
    fingerprint = key.get_fingerprint("sha256")
    audit(db, request, admin, "device.host_key_fetched", "device", device.id, {"fingerprint": fingerprint})
    await db.commit()
    algorithm = key.get_algorithm()
    key_file = {"ssh-ed25519": "ed25519", "ssh-rsa": "rsa"}.get(algorithm, "ecdsa")
    return HostKeyOut(
        fingerprint=fingerprint,
        key_type=algorithm,
        verify_command=f"ssh-keygen -lf /etc/ssh/ssh_host_{key_file}_key.pub",
    )


@router.post("/{device_id}/host-key/confirm", response_model=DeviceOut)
async def confirm_host_key(
    device_id: int,
    body: HostKeyConfirmIn,
    request: Request,
    admin: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> DeviceOut:
    device = await _get_device(db, device_id)
    if not device.pending_host_key:
        raise HTTPException(400, "Prvo preuzmite host ključ sa uređaja.")
    pending = asyncssh.import_public_key(device.pending_host_key)
    fingerprint = pending.get_fingerprint("sha256")
    if body.fingerprint.strip() != fingerprint:
        raise HTTPException(400, "Otisak se ne poklapa sa preuzetim ključem. Ponovo preuzmite ključ.")
    previous = device.host_key_fingerprint
    device.host_key = device.pending_host_key
    device.host_key_fingerprint = fingerprint
    device.host_key_confirmed_at = utcnow()
    device.host_key_confirmed_by = admin.username
    device.pending_host_key = None
    action = "device.host_key_changed" if previous and previous != fingerprint else "device.host_key_confirmed"
    audit(db, request, admin, action, "device", device.id, {"fingerprint": fingerprint, "previous": previous})
    await db.commit()
    await db.refresh(device)
    await _resync(db, device)
    return to_out(device, await _default_interval(db))


@router.post("/{device_id}/test-connection", response_model=TestResultOut)
async def test_connection(
    device_id: int, request: Request, user: User = Depends(operator_or_admin), db: AsyncSession = Depends(get_db)
) -> TestResultOut:
    device = await _get_device(db, device_id)
    if not collector.is_ready(device):
        raise HTTPException(400, "Uređaj nema SSH ključ ili potvrđen host ključ.")
    device_name = device.name
    audit(db, request, user, "device.test_connection", "device", device_id)
    await db.commit()
    run_id = await collector.run_collection(device_id, "test", user.username)
    if run_id is None:
        raise HTTPException(409, "Prikupljanje za ovaj uređaj je već u toku. Pokušajte ponovo za trenutak.")
    run = await db.get(CollectionRun, run_id)
    assert run is not None
    caps = await collector.capabilities_for(device_id)
    return TestResultOut(run=_run_out(run, device_name), capabilities=[CapabilityOut.model_validate(c) for c in caps])


@router.post("/{device_id}/collect", status_code=202)
async def collect_now(
    device_id: int, request: Request, user: User = Depends(operator_or_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    device = await _get_device(db, device_id)
    if not collector.is_ready(device):
        raise HTTPException(400, "Uređaj nema SSH ključ ili potvrđen host ključ.")
    if collector.is_running(device.id):
        raise HTTPException(409, "Prikupljanje za ovaj uređaj je već u toku.")
    audit(db, request, user, "device.collect_manual", "device", device.id)
    await db.commit()
    task = asyncio.create_task(collector.run_collection(device.id, "manual", user.username))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return {"message": "Prikupljanje je pokrenuto."}


@router.get("/{device_id}/runs", response_model=list[RunOut])
async def list_runs(
    device_id: int,
    limit: int = Query(50, ge=1, le=500),
    _: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RunOut]:
    device = await _get_device(db, device_id)
    runs = await db.scalars(
        select(CollectionRun).where(CollectionRun.device_id == device_id)
        .order_by(CollectionRun.started_at.desc()).limit(limit)
    )
    return [_run_out(r, device.name) for r in runs]
