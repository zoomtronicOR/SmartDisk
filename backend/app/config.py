from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Podešavanja iz okruženja (/etc/smartdisk/smartdisk.env), prefiks SMARTDISK_."""

    model_config = SettingsConfigDict(env_prefix="SMARTDISK_")

    database_url: str = "postgresql+asyncpg://smartdisk@/smartdisk?host=/var/run/postgresql"
    # Fernet ključ kojim se šifruju SSH privatni ključevi u bazi. Čuva se van baze.
    master_key: str

    session_idle_minutes: int = 30
    session_max_hours: int = 12
    cookie_secure: bool = True

    login_max_failures: int = 5
    login_lock_minutes: int = 15
    login_rate_per_ip: int = 10
    login_rate_window_seconds: int = 300

    max_parallel_ssh: int = 4
    max_command_output_bytes: int = 2_000_000

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
