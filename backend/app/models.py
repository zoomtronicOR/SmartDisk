"""SQLAlchemy modeli: korisnici, sesije, uređaji, prikupljanja, audit, podešavanja (Faza 1); diskovi, SMART, skladište (Faza 2); dnevni agregati (Faza 3); zdravlje, alarmi, notifikacije (Faza 4)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True)}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    platform: Mapped[str] = mapped_column(String(32))
    host: Mapped[str] = mapped_column(String(253))
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_username: Mapped[str] = mapped_column(String(64))
    auth_method: Mapped[str] = mapped_column(String(16), default="key")

    # Privatni ključ i passphrase su šifrovani master ključem (Fernet); nikad se ne vraćaju kroz API.
    encrypted_private_key: Mapped[str | None] = mapped_column(Text)
    encrypted_passphrase: Mapped[str | None] = mapped_column(Text)
    public_key: Mapped[str | None] = mapped_column(Text)

    host_key: Mapped[str | None] = mapped_column(Text)
    host_key_fingerprint: Mapped[str | None] = mapped_column(String(128))
    host_key_confirmed_at: Mapped[datetime | None]
    host_key_confirmed_by: Mapped[str | None] = mapped_column(String(64))
    # Ključ preuzet sa uređaja koji administrator još nije potvrdio.
    pending_host_key: Mapped[str | None] = mapped_column(Text)

    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Belgrade")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # NULL znači: koristi globalni podrazumevani interval.
    collection_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    connect_timeout: Mapped[int] = mapped_column(Integer, default=15)
    command_timeout: Mapped[int] = mapped_column(Integer, default=60)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    location: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    os_info: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    last_seen_at: Mapped[datetime | None]
    last_success_at: Mapped[datetime | None]
    last_failure_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None]


class DeviceCapability(Base):
    __tablename__ = "device_capabilities"
    __table_args__ = (UniqueConstraint("device_id", "capability"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    capability: Mapped[str] = mapped_column(String(64))
    available: Mapped[bool] = mapped_column(Boolean)
    details: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime]


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    __table_args__ = (Index("ix_collection_runs_device_started", "device_id", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    trigger: Mapped[str] = mapped_column(String(16))  # scheduled / manual / test
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # running / success / partial / failed
    disks_found: Mapped[int | None] = mapped_column(Integer)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    error_kind: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    initiated_by: Mapped[str | None] = mapped_column(String(64))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(64))


# --- Faza 2: diskovi, SMART očitavanja i skladište ---


class Disk(Base):
    """Fizički disk na uređaju. Identitet je WWN/EUI/serijski broj, pa disk zadržava istoriju i kada promeni putanju."""

    __tablename__ = "disks"
    __table_args__ = (UniqueConstraint("device_id", "stable_identifier"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    stable_identifier: Mapped[str] = mapped_column(String(255))
    device_path: Mapped[str] = mapped_column(String(128))
    smart_type: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(255))
    vendor: Mapped[str | None] = mapped_column(String(255))
    serial_number: Mapped[str | None] = mapped_column(String(128))
    wwn: Mapped[str | None] = mapped_column(String(64))
    firmware: Mapped[str | None] = mapped_column(String(64))
    disk_type: Mapped[str] = mapped_column(String(16), default="unknown")
    interface_type: Mapped[str | None] = mapped_column(String(64))
    capacity_bytes: Mapped[int | None] = mapped_column(BigInteger)
    rotation_rate: Mapped[int | None] = mapped_column(Integer)
    form_factor: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    is_present: Mapped[bool] = mapped_column(Boolean, default=True)
    latest_sample_id: Mapped[int | None] = mapped_column(BigInteger)
    # „Zdravlje diska” (spec. §8.8): excellent / good / attention / endangered / critical / unknown
    health_level: Mapped[str | None] = mapped_column(String(16))
    health_score: Mapped[int | None] = mapped_column(Integer)
    health_reasons: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    health_updated_at: Mapped[datetime | None]
    # Poslednji kompletan izlaz alata (čuva se samo poslednji, da baza ne raste nepotrebno).
    last_raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class DiskSample(Base):
    """Jedno SMART očitavanje diska. NULL znači „nije dostupno”, nikad „0” ili „ispravno”."""

    __tablename__ = "disk_samples"
    __table_args__ = (Index("ix_disk_samples_disk_collected", "disk_id", "collected_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    disk_id: Mapped[int] = mapped_column(ForeignKey("disks.id", ondelete="CASCADE"))
    run_id: Mapped[int | None] = mapped_column(BigInteger)
    collected_at: Mapped[datetime] = mapped_column(index=True)
    device_path: Mapped[str | None] = mapped_column(String(128))
    smart_available: Mapped[bool] = mapped_column(Boolean)
    smart_health: Mapped[str] = mapped_column(String(16))  # passed/failed/unknown/unavailable/standby
    smart_message: Mapped[str | None] = mapped_column(Text)
    temperature_c: Mapped[int | None] = mapped_column(Integer)
    power_on_hours: Mapped[int | None] = mapped_column(Integer)
    power_cycles: Mapped[int | None] = mapped_column(Integer)
    reallocated_sectors: Mapped[int | None] = mapped_column(BigInteger)
    pending_sectors: Mapped[int | None] = mapped_column(BigInteger)
    uncorrectable_sectors: Mapped[int | None] = mapped_column(BigInteger)
    crc_errors: Mapped[int | None] = mapped_column(BigInteger)
    reported_uncorrect: Mapped[int | None] = mapped_column(BigInteger)
    load_cycles: Mapped[int | None] = mapped_column(BigInteger)
    start_stop_count: Mapped[int | None] = mapped_column(BigInteger)
    ssd_life_left: Mapped[int | None] = mapped_column(Integer)
    total_lbas_written: Mapped[int | None] = mapped_column(BigInteger)
    percentage_used: Mapped[int | None] = mapped_column(Integer)
    available_spare: Mapped[int | None] = mapped_column(Integer)
    available_spare_threshold: Mapped[int | None] = mapped_column(Integer)
    media_errors: Mapped[int | None] = mapped_column(BigInteger)
    critical_warning: Mapped[int | None] = mapped_column(Integer)
    unsafe_shutdowns: Mapped[int | None] = mapped_column(BigInteger)
    data_units_read: Mapped[int | None] = mapped_column(BigInteger)
    data_units_written: Mapped[int | None] = mapped_column(BigInteger)
    host_read_commands: Mapped[int | None] = mapped_column(BigInteger)
    host_write_commands: Mapped[int | None] = mapped_column(BigInteger)
    controller_busy_time: Mapped[int | None] = mapped_column(BigInteger)
    error_log_entries: Mapped[int | None] = mapped_column(BigInteger)
    warning_temp_time: Mapped[int | None] = mapped_column(Integer)
    critical_temp_time: Mapped[int | None] = mapped_column(Integer)
    error_log_count: Mapped[int | None] = mapped_column(Integer)
    self_test_running: Mapped[bool] = mapped_column(Boolean, default=False)
    self_test_status: Mapped[str | None] = mapped_column(String(255))
    # SATA/SAS atributi: id, name, value, worst, thresh, raw, raw_string, prefail, when_failed
    attributes: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # Zdravlje diska izračunato posle ovog očitavanja (istorija nivoa, Faza 4)
    health_level: Mapped[str | None] = mapped_column(String(16))
    health_score: Mapped[int | None] = mapped_column(Integer)


class SmartTest(Base):
    """Rezultat SMART self-testa iz loga diska (aplikacija testove ne pokreće)."""

    __tablename__ = "smart_tests"
    __table_args__ = (UniqueConstraint("disk_id", "test_type", "status", "lifetime_hours"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    disk_id: Mapped[int] = mapped_column(ForeignKey("disks.id", ondelete="CASCADE"), index=True)
    test_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(128))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    lifetime_hours: Mapped[int] = mapped_column(Integer, default=-1)
    remaining_percent: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime]


class StoragePool(Base):
    """ZFS pool, LVM VG/thin pool, mdadm niz, Proxmox storage ili Synology volumen."""

    __tablename__ = "storage_pools"
    __table_args__ = (UniqueConstraint("device_id", "technology", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    technology: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(64))
    healthy: Mapped[bool | None] = mapped_column(Boolean)
    redundancy: Mapped[str | None] = mapped_column(String(128))
    capacity_bytes: Mapped[int | None] = mapped_column(BigInteger)
    used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    free_bytes: Mapped[int | None] = mapped_column(BigInteger)
    read_errors: Mapped[int | None] = mapped_column(BigInteger)
    write_errors: Mapped[int | None] = mapped_column(BigInteger)
    checksum_errors: Mapped[int | None] = mapped_column(BigInteger)
    message: Mapped[str | None] = mapped_column(Text)
    data_errors: Mapped[str | None] = mapped_column(Text)
    scan_type: Mapped[str | None] = mapped_column(String(32))
    scan_state: Mapped[str | None] = mapped_column(String(32))
    scan_progress: Mapped[float | None]
    scan_errors: Mapped[int | None] = mapped_column(Integer)
    scan_finished_at: Mapped[str | None] = mapped_column(String(64))
    scan_text: Mapped[str | None] = mapped_column(Text)
    members: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    is_present: Mapped[bool] = mapped_column(Boolean, default=True)


class PoolSample(Base):
    __tablename__ = "pool_samples"
    __table_args__ = (Index("ix_pool_samples_pool_collected", "pool_id", "collected_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("storage_pools.id", ondelete="CASCADE"))
    collected_at: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(64))
    healthy: Mapped[bool | None] = mapped_column(Boolean)
    read_errors: Mapped[int | None] = mapped_column(BigInteger)
    write_errors: Mapped[int | None] = mapped_column(BigInteger)
    checksum_errors: Mapped[int | None] = mapped_column(BigInteger)
    capacity_bytes: Mapped[int | None] = mapped_column(BigInteger)
    used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    free_bytes: Mapped[int | None] = mapped_column(BigInteger)
    scan_type: Mapped[str | None] = mapped_column(String(32))
    scan_state: Mapped[str | None] = mapped_column(String(32))
    scan_progress: Mapped[float | None]
    scan_errors: Mapped[int | None] = mapped_column(Integer)


# --- Faza 3: dnevni agregati (čuvaju se i posle brisanja sirovih merenja) ---


class DiskDaily(Base):
    """Dnevni agregat SMART očitavanja (spec. §9.2). Dan je po vremenskoj zoni prikaza."""

    __tablename__ = "disk_daily"

    disk_id: Mapped[int] = mapped_column(ForeignKey("disks.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    samples: Mapped[int] = mapped_column(Integer)
    smart_failed_samples: Mapped[int] = mapped_column(Integer, default=0)
    temperature_min: Mapped[int | None] = mapped_column(Integer)
    temperature_max: Mapped[int | None] = mapped_column(Integer)
    temperature_avg: Mapped[float | None]
    power_on_hours: Mapped[int | None] = mapped_column(Integer)
    power_cycles: Mapped[int | None] = mapped_column(Integer)
    reallocated_sectors: Mapped[int | None] = mapped_column(BigInteger)
    pending_sectors: Mapped[int | None] = mapped_column(BigInteger)
    uncorrectable_sectors: Mapped[int | None] = mapped_column(BigInteger)
    crc_errors: Mapped[int | None] = mapped_column(BigInteger)
    reported_uncorrect: Mapped[int | None] = mapped_column(BigInteger)
    media_errors: Mapped[int | None] = mapped_column(BigInteger)
    error_log_entries: Mapped[int | None] = mapped_column(BigInteger)
    unsafe_shutdowns: Mapped[int | None] = mapped_column(BigInteger)
    percentage_used: Mapped[int | None] = mapped_column(Integer)
    available_spare: Mapped[int | None] = mapped_column(Integer)
    ssd_life_left: Mapped[int | None] = mapped_column(Integer)
    data_units_written: Mapped[int | None] = mapped_column(BigInteger)
    total_lbas_written: Mapped[int | None] = mapped_column(BigInteger)


class PoolDaily(Base):
    __tablename__ = "pool_daily"

    pool_id: Mapped[int] = mapped_column(ForeignKey("storage_pools.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    samples: Mapped[int] = mapped_column(Integer)
    unhealthy_samples: Mapped[int] = mapped_column(Integer, default=0)
    capacity_bytes: Mapped[int | None] = mapped_column(BigInteger)
    used_bytes: Mapped[int | None] = mapped_column(BigInteger)  # maksimum u danu
    used_bytes_avg: Mapped[float | None]
    free_bytes: Mapped[int | None] = mapped_column(BigInteger)  # minimum u danu
    read_errors: Mapped[int | None] = mapped_column(BigInteger)
    write_errors: Mapped[int | None] = mapped_column(BigInteger)
    checksum_errors: Mapped[int | None] = mapped_column(BigInteger)


# --- Faza 4: događaji (alarmi), istorija alarma, notifikacije ---


class Event(Base):
    """Alarm (spec. §8.9, §11.3). Jedan otvoren alarm po fingerprint-u; ponavljanje povećava brojač."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_status_severity", "status", "severity"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(255), index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    disk_id: Mapped[int | None] = mapped_column(ForeignKey("disks.id", ondelete="CASCADE"), index=True)
    pool_id: Mapped[int | None] = mapped_column(ForeignKey("storage_pools.id", ondelete="CASCADE"))
    severity: Mapped[str] = mapped_column(String(16))  # info / warning / high / critical
    max_severity: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32))  # smart / nvme / temperature / pool / device / inventory / data
    rule: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    metric: Mapped[str | None] = mapped_column(String(64))
    previous_value: Mapped[float | None]
    current_value: Mapped[float | None]
    period: Mapped[str | None] = mapped_column(String(32))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open / acknowledged / resolved
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    acknowledged_by: Mapped[str | None] = mapped_column(String(64))
    acknowledged_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[str | None] = mapped_column(String(64))  # NULL = automatski (uslov više ne važi)
    last_notified_at: Mapped[datetime | None]
    notified_severity: Mapped[str | None] = mapped_column(String(16))


class EventHistory(Base):
    """Istorija promena alarma: nastanak, eskalacija, potvrda, komentar, rešavanje."""

    __tablename__ = "event_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    action: Mapped[str] = mapped_column(String(32))  # opened / escalated / deescalated / acknowledged / comment / resolved / reopened
    username: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str | None] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)


class PushSubscription(Base):
    """Web Push pretplata pregledača (spec. §13), sa izborom ozbiljnosti, uređaja i utišavanjem."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    min_severity: Mapped[str] = mapped_column(String(16), default="warning")
    device_ids: Mapped[list[int] | None] = mapped_column(JSONB)  # NULL = svi uređaji
    muted_until: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_success_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), index=True)
    channel: Mapped[str] = mapped_column(String(16))  # push / mqtt
    target: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    status: Mapped[str] = mapped_column(String(16))  # sent / failed / skipped
    error_message: Mapped[str | None] = mapped_column(Text)
