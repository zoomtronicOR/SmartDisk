"""Pydantic šeme za API. Poruke grešaka validacije su na srpskom."""

import ipaddress
import re
from datetime import datetime
from typing import Any, Literal
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .constants import INTERVAL_MAX_MINUTES, INTERVAL_MIN_MINUTES, PLATFORMS

Role = Literal["admin", "operator", "viewer"]

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
_SSH_USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")


def _validate_host(value: str) -> str:
    value = value.strip()
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if not _HOSTNAME_RE.match(value):
        raise ValueError("Neispravna IP adresa ili DNS ime.")
    return value.lower()


def _validate_timezone(value: str) -> str:
    if value not in available_timezones():
        raise ValueError("Nepoznata vremenska zona.")
    return value


def _validate_interval(value: int | None) -> int | None:
    if value is not None and not INTERVAL_MIN_MINUTES <= value <= INTERVAL_MAX_MINUTES:
        raise ValueError(f"Interval mora biti između {INTERVAL_MIN_MINUTES} minuta i 7 dana.")
    return value


# --- Autentifikacija i korisnici ---


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    # Podaci o računaru/pregledaču za audit log (ekran, jezik, zona, OS preko Client Hints); bez tajni.
    client: dict[str, Any] | None = None


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    role: Role
    is_active: bool
    must_change_password: bool
    failed_login_count: int
    locked_until: datetime | None
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    username: str
    email: str | None = Field(default=None, max_length=255)
    role: Role
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not _USERNAME_RE.match(value):
            raise ValueError("Korisničko ime: 2–64 znaka, mala slova, cifre, tačka, crtica ili donja crta.")
        return value


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    role: Role | None = None
    is_active: bool | None = None


class PasswordResetIn(BaseModel):
    new_password: str = Field(min_length=1, max_length=256)


# --- Uređaji ---

Platform = Literal["truenas_scale", "truenas_core", "proxmox", "synology"]


def _clean_ssh_username(value: str) -> str:
    value = value.strip()
    if not _SSH_USERNAME_RE.match(value):
        raise ValueError("Neispravno SSH korisničko ime.")
    return value


def _clean_tags(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in value:
        tag = tag.strip()
        if len(tag) > 40:
            raise ValueError("Oznaka može imati najviše 40 znakova.")
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Naziv je obavezan.")
    return value


class DeviceBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform: Platform
    host: str
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_username: str
    timezone: str = "Europe/Belgrade"
    collection_interval_minutes: int | None = None
    connect_timeout: int = Field(default=15, ge=3, le=120)
    command_timeout: int = Field(default=60, ge=5, le=900)
    tags: list[str] = Field(default_factory=list, max_length=20)
    location: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("host")
    @classmethod
    def check_host(cls, value: str) -> str:
        return _validate_host(value)

    @field_validator("ssh_username")
    @classmethod
    def check_ssh_username(cls, value: str) -> str:
        return _clean_ssh_username(value)

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str) -> str:
        return _validate_timezone(value)

    @field_validator("collection_interval_minutes")
    @classmethod
    def check_interval(cls, value: int | None) -> int | None:
        return _validate_interval(value)

    @field_validator("tags")
    @classmethod
    def check_tags(cls, value: list[str]) -> list[str]:
        return _clean_tags(value)


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    platform: Platform | None = None
    host: str | None = None
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    ssh_username: str | None = None
    timezone: str | None = None
    enabled: bool | None = None
    # Eksplicitno slanje null znači "koristi globalni interval"; zato se proverava model_fields_set.
    collection_interval_minutes: int | None = None
    connect_timeout: int | None = Field(default=None, ge=3, le=120)
    command_timeout: int | None = Field(default=None, ge=5, le=900)
    tags: list[str] | None = Field(default=None, max_length=20)
    location: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)

    @field_validator("host")
    @classmethod
    def check_host(cls, value: str | None) -> str | None:
        return None if value is None else _validate_host(value)

    @field_validator("ssh_username")
    @classmethod
    def check_ssh_username(cls, value: str | None) -> str | None:
        return None if value is None else _clean_ssh_username(value)

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str | None) -> str | None:
        return None if value is None else _validate_timezone(value)

    @field_validator("collection_interval_minutes")
    @classmethod
    def check_interval(cls, value: int | None) -> int | None:
        return _validate_interval(value)

    @field_validator("tags")
    @classmethod
    def check_tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_tags(value)


class CredentialsIn(BaseModel):
    private_key: str = Field(min_length=1, max_length=16384)
    passphrase: str | None = Field(default=None, max_length=1024)


class GeneratedKeyOut(BaseModel):
    public_key: str


class HostKeyOut(BaseModel):
    fingerprint: str
    key_type: str
    verify_command: str


class HostKeyConfirmIn(BaseModel):
    fingerprint: str = Field(min_length=1, max_length=128)


class CapabilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    capability: str
    available: bool
    details: str | None
    checked_at: datetime


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    device_name: str | None = None
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    status: str
    disks_found: int | None
    errors_count: int
    error_kind: str | None
    error_message: str | None
    details: dict[str, Any] | None
    initiated_by: str | None


DeviceStatus = Literal["not_configured", "disabled", "waiting", "ok", "error"]


class DeviceOut(BaseModel):
    id: int
    name: str
    platform: str
    platform_label: str
    host: str
    ssh_port: int
    ssh_username: str
    auth_method: str
    has_credentials: bool
    public_key: str | None
    host_key_fingerprint: str | None
    host_key_confirmed_at: datetime | None
    host_key_confirmed_by: str | None
    has_pending_host_key: bool
    timezone: str
    enabled: bool
    collection_interval_minutes: int | None
    effective_interval_minutes: int
    connect_timeout: int
    command_timeout: int
    tags: list[str]
    location: str | None
    note: str | None
    os_info: str | None
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    next_run_at: datetime | None
    running: bool
    status: DeviceStatus


class DeviceDetailOut(DeviceOut):
    capabilities: list[CapabilityOut]
    last_runs: list[RunOut]


class TestResultOut(BaseModel):
    run: RunOut
    capabilities: list[CapabilityOut]


# --- Podešavanja, audit, sistem ---


class CollectionSettings(BaseModel):
    default_interval_minutes: int
    raw_retention_days: int
    min_minutes: int = INTERVAL_MIN_MINUTES
    max_minutes: int = INTERVAL_MAX_MINUTES


class CollectionSettingsIn(BaseModel):
    default_interval_minutes: int
    raw_retention_days: int | None = None

    @field_validator("raw_retention_days")
    @classmethod
    def check_retention(cls, value: int | None) -> int | None:
        if value is not None and not 30 <= value <= 3650:
            raise ValueError("Period čuvanja mora biti između 30 dana i 10 godina.")
        return value

    @field_validator("default_interval_minutes")
    @classmethod
    def check_interval(cls, value: int) -> int:
        _validate_interval(value)
        return value


class GeneralSettings(BaseModel):
    timezone: str

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str) -> str:
        return _validate_timezone(value)


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    source_ip: str | None
    created_at: datetime
    details: dict[str, Any] | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int


class Meta(BaseModel):
    platforms: dict[str, str] = PLATFORMS
