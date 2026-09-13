from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

# COLLECTION.md: the observation day is the calendar day in Europe/Madrid.
OBSERVATION_ZONE = ZoneInfo("Europe/Madrid")

_DEFAULT_MIGRATIONS = (
    Path(__file__).resolve().parents[4] / "packages" / "db" / "drizzle"
)


@dataclass(frozen=True)
class Settings:
    database_url: str
    language: str = "ca"
    request_interval: float = 0.5
    stale_hours: int = 72
    discontinued_days: int = 14
    detail_daily_budget: int = 3000
    user_agent: str = "mercapy-web/0.1 (+https://mercapy.joeltaylor.business)"
    migrations_dir: Path = _DEFAULT_MIGRATIONS

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        database_url = env.get("DATABASE_URL")
        if not database_url:
            raise SystemExit("DATABASE_URL is required")
        return cls(
            database_url=database_url,
            language=env.get("MERCAPY_LANGUAGE", cls.language),
            request_interval=float(
                env.get("MERCAPY_REQUEST_INTERVAL", cls.request_interval)
            ),
            stale_hours=int(env.get("MERCAPY_STALE_HOURS", cls.stale_hours)),
            discontinued_days=int(
                env.get("MERCAPY_DISCONTINUED_DAYS", cls.discontinued_days)
            ),
            detail_daily_budget=int(
                env.get("MERCAPY_DETAIL_DAILY_BUDGET", cls.detail_daily_budget)
            ),
            user_agent=env.get("MERCAPY_USER_AGENT", cls.user_agent),
            migrations_dir=Path(env.get("MIGRATIONS_DIR", _DEFAULT_MIGRATIONS)),
        )
