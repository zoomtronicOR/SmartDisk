"""Šifrovanje tajni u mirovanju (SSH privatni ključevi, passphrase, kasnije MQTT lozinka)."""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().master_key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Tajna ne može da se dešifruje – proverite SMARTDISK_MASTER_KEY.") from exc
