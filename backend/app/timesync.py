"""Provera tačnosti vremena (spec. §18.1).

U unprivileged LXC-u sat dolazi od Proxmox hosta i ne može se podešavati iz kontejnera. Zato aplikacija
proverava status sinhronizacije (timedatectl) i meri odstupanje od podešenog NTP servera (SNTP upit).
"""

import asyncio
import logging
import socket
import struct
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .models import utcnow

log = logging.getLogger("smartdisk.time")

NTP_EPOCH_DELTA = 2_208_988_800  # sekunde između 1900-01-01 i 1970-01-01


@dataclass
class TimeStatus:
    checked_at: datetime | None = None
    ntp_server: str | None = None
    offset_ms: float | None = None  # lokalni sat − NTP (pozitivno = lokalni sat žuri)
    delay_ms: float | None = None
    stratum: int | None = None
    host_synchronized: bool | None = None  # timedatectl NTPSynchronized (sat hosta)
    error: str | None = None


_status = TimeStatus()


def status() -> dict[str, Any]:
    return asdict(_status)


def _sntp(server: str, timeout: float = 3.0) -> tuple[float, float, int]:
    """Jedan SNTP upit (RFC 4330). Vraća (odstupanje s, kašnjenje s, stratum)."""
    packet = bytearray(48)
    packet[0] = 0x23  # LI=0, VN=4, Mode=3 (klijent)
    addr = socket.getaddrinfo(server, 123, type=socket.SOCK_DGRAM)[0]
    with socket.socket(addr[0], socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        t1 = time.time()
        sock.sendto(bytes(packet), addr[4])
        data, _ = sock.recvfrom(512)
        t4 = time.time()
    if len(data) < 48:
        raise ValueError("Neispravan NTP odgovor.")
    stratum = data[1]
    if stratum == 0:
        raise ValueError("NTP server je odbio upit (kiss-o'-death).")

    def ts(offset: int) -> float:
        sec, frac = struct.unpack("!II", data[offset:offset + 8])
        return sec - NTP_EPOCH_DELTA + frac / 2**32

    t2, t3 = ts(32), ts(40)
    offset = ((t2 - t1) + (t3 - t4)) / 2  # NTP − lokalno
    delay = (t4 - t1) - (t3 - t2)
    return -offset, delay, stratum


def _host_synchronized() -> bool | None:
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return {"yes": True, "no": False}.get(out)
    except (OSError, subprocess.SubprocessError):
        return None


async def check(server: str) -> TimeStatus:
    global _status
    new = TimeStatus(checked_at=utcnow(), ntp_server=server)
    new.host_synchronized = await asyncio.to_thread(_host_synchronized)
    try:
        offset, delay, stratum = await asyncio.to_thread(_sntp, server)
        new.offset_ms, new.delay_ms, new.stratum = round(offset * 1000, 1), round(delay * 1000, 1), stratum
    except (OSError, ValueError) as exc:
        new.error = f"NTP server {server} nije odgovorio: {exc}"
    _status = new
    if new.error:
        log.warning(new.error)
    return new
