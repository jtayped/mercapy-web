from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import psycopg
from psycopg.rows import DictRow, dict_row

from collector.config import OBSERVATION_ZONE

Connection = psycopg.Connection[DictRow]
Row = dict[str, Any]


def connect(database_url: str) -> Connection:
    return psycopg.connect(database_url, row_factory=dict_row, autocommit=True)


def now_utc() -> datetime:
    return datetime.now(UTC)


def observation_day(instant: datetime) -> date:
    return instant.astimezone(OBSERVATION_ZONE).date()


def fetch_one(conn: Connection, query: str, params: Any = None) -> Row | None:
    return conn.execute(query, params).fetchone()


def fetch_all(conn: Connection, query: str, params: Any = None) -> list[Row]:
    return conn.execute(query, params).fetchall()
