from __future__ import annotations

from collector.config import Settings
from collector.db import Connection, fetch_all
from collector.migrations import apply_migrations, load_migrations


def test_migrations_are_recorded_the_way_drizzle_records_them(
    session_conn: Connection, settings: Settings
) -> None:
    rows = fetch_all(
        session_conn,
        "select hash, created_at from drizzle.__drizzle_migrations order by created_at",
    )
    expected = load_migrations(settings.migrations_dir)
    assert [(row["hash"], row["created_at"]) for row in rows] == [
        (migration.digest, migration.when) for migration in expected
    ]
    assert apply_migrations(session_conn, settings.migrations_dir) == []
