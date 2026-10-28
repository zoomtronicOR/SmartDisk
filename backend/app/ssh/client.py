"""SSH pristup uređajima: preuzimanje host ključa, konekcija uz obaveznu proveru host ključa, izvršavanje komandi.

Komande se uvek sastavljaju iz unapred definisanih šablona; korisnički unos se nikad ne prosleđuje shell-u.
"""

import asyncio
import logging
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import asyncssh

from ..config import get_settings

log = logging.getLogger("smartdisk.ssh")


class SSHError(Exception):
    """Greška SSH sloja sa vrstom (za statistiku) i porukom za korisnika na srpskom."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass
class ConnInfo:
    host: str
    port: int
    username: str
    private_key: str
    passphrase: str | None
    host_key: str
    connect_timeout: int


@dataclass
class CommandResult:
    exit_status: int | None
    stdout: str
    stderr: str
    truncated: bool


def _map_error(exc: BaseException, timeout: int) -> SSHError:
    if isinstance(exc, SSHError):
        return exc
    if isinstance(exc, asyncssh.HostKeyNotVerifiable):
        return SSHError(
            "host_key_mismatch",
            "Host ključ uređaja se ne poklapa sa potvrđenim otiskom. Moguća je reinstalacija ili zamena "
            "servera - proverite uređaj, pa ponovo preuzmite i potvrdite ključ.",
        )
    if isinstance(exc, asyncssh.PermissionDenied):
        return SSHError(
            "auth_failed",
            "SSH prijava je odbijena. Proverite korisničko ime i da li je javni ključ dodat u authorized_keys.",
        )
    if isinstance(exc, TimeoutError):  # obuhvata i asyncio.TimeoutError
        return SSHError("timeout", f"Isteklo je vreme za povezivanje ({timeout} s).")
    if isinstance(exc, ConnectionRefusedError):
        return SSHError("unreachable", "Konekcija je odbijena - SSH servis nije dostupan na tom portu.")
    if isinstance(exc, socket.gaierror):
        return SSHError("dns", "DNS ime uređaja ne može da se razreši.")
    if isinstance(exc, OSError):
        return SSHError("unreachable", f"Uređaj nije dostupan: {exc.strerror or exc}")
    if isinstance(exc, asyncssh.Error):
        return SSHError("ssh_error", f"SSH greška: {exc.reason}")
    return SSHError("unexpected", f"Neočekivana greška: {type(exc).__name__}")


# Redosled kojim se traži host ključ: prvo moderni algoritmi, RSA samo ako drugog nema.
HOST_KEY_ALGS = [
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "rsa-sha2-512",
    "rsa-sha2-256",
    "ssh-rsa",
]


async def fetch_host_key(host: str, port: int, timeout: int) -> asyncssh.SSHKey:
    """Preuzima javni host ključ bez prijave, radi potvrde otiska od strane administratora."""
    try:
        key = await asyncio.wait_for(
            asyncssh.get_server_host_key(host, port, server_host_key_algs=HOST_KEY_ALGS), timeout
        )
    except Exception as exc:
        raise _map_error(exc, timeout) from exc
    if key is None:
        raise SSHError("ssh_error", "Uređaj nije vratio host ključ.")
    return key


def load_private_key(private_key: str, passphrase: str | None) -> asyncssh.SSHKey:
    try:
        return asyncssh.import_private_key(private_key, passphrase or None)
    except (asyncssh.KeyImportError, ValueError) as exc:
        raise SSHError(
            "credentials", "Privatni ključ ne može da se učita (neispravan format ili pogrešna passphrase)."
        ) from exc


@asynccontextmanager
async def connect(info: ConnInfo) -> AsyncIterator[asyncssh.SSHClientConnection]:
    client_key = load_private_key(info.private_key, info.passphrase)
    try:
        trusted = asyncssh.import_public_key(info.host_key)
    except (asyncssh.KeyImportError, ValueError) as exc:
        raise SSHError("host_key", "Sačuvani host ključ je neispravan - ponovo ga preuzmite i potvrdite.") from exc

    try:
        conn = await asyncio.wait_for(
            asyncssh.connect(
                info.host,
                port=info.port,
                username=info.username,
                client_keys=[client_key],
                known_hosts=([trusted], [], []),
                agent_path=None,
                preferred_auth="publickey",
                connect_timeout=info.connect_timeout,
                login_timeout=info.connect_timeout,
            ),
            info.connect_timeout + 5,
        )
    except Exception as exc:
        raise _map_error(exc, info.connect_timeout) from exc

    try:
        yield conn
    finally:
        conn.close()
        try:
            await asyncio.wait_for(conn.wait_closed(), 5)
        except Exception:  # zatvaranje ne sme da obori ciklus
            log.debug("Zatvaranje SSH konekcije ka %s nije završeno uredno", info.host)


def _limit(text: str, limit: int) -> tuple[str, bool]:
    if len(text) > limit:
        return text[:limit], True
    return text, False


async def run_command(conn: asyncssh.SSHClientConnection, command: str, timeout: int) -> CommandResult:
    limit = get_settings().max_command_output_bytes
    try:
        result = await asyncio.wait_for(
            conn.run(command, check=False, encoding="utf-8", errors="replace"), timeout
        )
    except TimeoutError as exc:
        raise SSHError("command_timeout", f"Komanda nije završena za {timeout} s.") from exc
    except asyncssh.Error as exc:
        raise SSHError("ssh_error", f"SSH greška pri izvršavanju komande: {exc.reason}") from exc

    stdout, cut_out = _limit(str(result.stdout or ""), limit)
    stderr, cut_err = _limit(str(result.stderr or ""), limit)
    return CommandResult(result.exit_status, stdout, stderr, cut_out or cut_err)
