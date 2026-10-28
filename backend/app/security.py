"""Lozinke (Argon2id), sesijski tokeni i ograničenje pokušaja prijave."""

import hashlib
import secrets
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # podrazumevano Argon2id

# Hash koji se proverava kada korisnik ne postoji, da vreme odgovora ne otkriva postojanje naloga.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

PASSWORD_MIN_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problem(password: str, username: str) -> str | None:
    """Vraća opis problema sa lozinkom ili None ako je lozinka prihvatljiva."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Lozinka mora imati najmanje {PASSWORD_MIN_LENGTH} znakova."
    if len(password) > 256:
        return "Lozinka je predugačka."
    if username and username.lower() in password.lower():
        return "Lozinka ne sme sadržati korisničko ime."
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if len(password) < 16 and classes < 3:
        return "Lozinka kraća od 16 znakova mora sadržati bar tri od: mala slova, velika slova, cifre, specijalne znakove."
    if len(set(password)) < 5:
        return "Lozinka je previše jednostavna."
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


class LoginRateLimiter:
    """Jednostavno ograničenje broja pokušaja prijave po IP adresi (u memoriji, jedan proces)."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        attempts = self._attempts[key]
        while attempts and now - attempts[0] > self.window:
            attempts.popleft()
        if len(attempts) >= self.max_attempts:
            return False
        attempts.append(now)
        return True

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)
