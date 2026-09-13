"""applies the sql migrations drizzle-kit generates into packages/db/drizzle.

the collector is the only writer, so it owns applying migrations too. the
journal table it keeps is the one drizzle-orm's own migrator uses (schema
`drizzle`, table `__drizzle_migrations`, sha256 of the file, the journal's
`when`), so `drizzle-kit` tooling and a future node migrator see the same
history. only the format of that table is drizzle's; the code here is ours.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from collector.db import Connection, fetch_one

BREAKPOINT = "--> statement-breakpoint"


@dataclass(frozen=True, slots=True)
class Migration:
    tag: str
    when: int
    sql: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


def load_migrations(directory: Path) -> list[Migration]:
    journal = json.loads((directory / "meta" / "_journal.json").read_text())
    migrations = [
        Migration(
            tag=entry["tag"],
            when=int(entry["when"]),
            sql=(directory / f"{entry['tag']}.sql").read_text(),
        )
        for entry in journal["entries"]
    ]
    return sorted(migrations, key=lambda migration: migration.when)


def apply_migrations(conn: Connection, directory: Path) -> list[str]:
    with conn.transaction():
        conn.execute("create schema if not exists drizzle")
        conn.execute(
            """
            create table if not exists drizzle.__drizzle_migrations (
                id serial primary key,
                hash text not null,
                created_at bigint
            )
            """
        )
    latest = fetch_one(
        conn, "select max(created_at) as created_at from drizzle.__drizzle_migrations"
    )
    applied_until = (latest or {}).get("created_at") or 0
    applied: list[str] = []
    for migration in load_migrations(directory):
        if migration.when <= applied_until:
            continue
        with conn.transaction():
            for statement in migration.sql.split(BREAKPOINT):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(
                "insert into drizzle.__drizzle_migrations (hash, created_at)"
                " values (%s, %s)",
                (migration.digest, migration.when),
            )
        applied.append(migration.tag)
    return applied
