"""warehouses and the postal codes that reach them (COLLECTION.md).

the historical list is an inactive seed. a warehouse is published after a
postal code resolves to it and a collection completes.
"""

from __future__ import annotations

import io
import time
import zipfile
from collections.abc import Callable, Iterable
from datetime import datetime

import httpx

from collector.client import resolve_warehouse
from collector.config import Settings
from collector.db import Connection, Row, fetch_all, fetch_one, now_utc

HISTORICAL_WAREHOUSES = (
    "mad1", "mad2", "bcn1", "alc1", "vlc1", "svq1",
    "4115", "3532", "2183", "4483", "4421", "3684", "3968", "4644", "4097", "4293",
    "2581", "4537", "4572", "2623", "4416", "4028", "2343", "4436", "4281", "4308",
    "2749", "3947", "3951", "3996", "4068", "4069", "4230", "4267", "4354", "4385",
    "4472", "4558", "4697",
)  # fmt: skip

Resolver = Callable[[str], str]

# COLLECTION.md: candidates come from geonames, attribution cc by 4.0.
GEONAMES_URL = "https://download.geonames.org/export/zip/ES.zip"


def seed_historical_warehouses(conn: Connection) -> int:
    created = 0
    for code in HISTORICAL_WAREHOUSES:
        result = conn.execute(
            "insert into warehouse (code, active, verified) values (%s, false, false)"
            " on conflict do nothing",
            (code,),
        )
        created += result.rowcount
    return created


def import_postal_codes(conn: Connection, lines: Iterable[str]) -> int:
    """geonames ES.txt is tab separated with the postal code in the second
    column; a bare list of codes works too."""

    values: set[str] = set()
    for line in lines:
        value = line.strip().split("\t")[1] if "\t" in line else line.strip()
        if len(value) == 5 and value.isdigit():
            values.add(value)
    created = 0
    for value in sorted(values):
        result = conn.execute(
            "insert into postal_code (postal_code, source) values (%s, 'geonames')"
            " on conflict do nothing",
            (value,),
        )
        created += result.rowcount
    return created


def resolve_postal_code(
    conn: Connection,
    settings: Settings,
    postal_code: str,
    *,
    source: str,
    resolver: Resolver | None = None,
    now: datetime | None = None,
) -> Row:
    current = now or now_utc()
    resolve = resolver or (lambda code: resolve_warehouse(settings, code))
    conn.execute(
        "insert into postal_code (postal_code, source) values (%s, %s)"
        " on conflict do nothing",
        (postal_code, source),
    )
    try:
        warehouse_code = resolve(postal_code)
    except Exception as error:
        conn.execute(
            """
            update postal_code set last_error = %s, last_checked_at = %s, source = %s
            where postal_code = %s
            """,
            (f"{type(error).__name__}: {error}", current, source, postal_code),
        )
    else:
        with conn.transaction():
            # a seeded code that a real postal code reaches stops being a seed.
            conn.execute(
                "insert into warehouse (code) values (%s)"
                " on conflict (code) do update set active = true",
                (warehouse_code,),
            )
            conn.execute(
                """
                update postal_code set warehouse_code = %s, resolved_at = %s,
                    last_checked_at = %s, last_error = '', source = %s
                where postal_code = %s
                """,
                (warehouse_code, current, current, source, postal_code),
            )
    row = fetch_one(
        conn, "select * from postal_code where postal_code = %s", (postal_code,)
    )
    assert row is not None  # noqa: S101
    return row


def discover_batch(
    conn: Connection,
    settings: Settings,
    *,
    limit: int,
    max_age_days: int,
    resolver: Resolver | None = None,
) -> list[Row]:
    # breadth first: the first unchecked code of every province (the first two
    # digits) goes before the second of any, and provinces with fewer resolved
    # codes go first, so the warehouse map covers the country early instead of
    # walking Álava to Zaragoza in order.
    candidates = fetch_all(
        conn,
        """
        with resolved as (
            select left(postal_code, 2) as province, count(*) as n
            from postal_code where warehouse_code is not null group by 1
        ),
        due as (
            select postal_code, source,
                row_number() over (
                    partition by left(postal_code, 2) order by postal_code
                ) as rank
            from postal_code
            where last_checked_at is null
               or last_checked_at <= now() - make_interval(days => %s)
        )
        select due.postal_code, due.source from due
        left join resolved on resolved.province = left(due.postal_code, 2)
        order by due.rank + coalesce(resolved.n, 0), due.postal_code
        limit %s
        """,
        (max_age_days, limit),
    )
    results: list[Row] = []
    for index, row in enumerate(candidates):
        if index and settings.request_interval:
            time.sleep(settings.request_interval)
        results.append(
            resolve_postal_code(
                conn,
                settings,
                row["postal_code"],
                source=row["source"],
                resolver=resolver,
            )
        )
    return results


def download_geonames(settings: Settings) -> list[str]:
    response = httpx.get(
        GEONAMES_URL, headers={"User-Agent": settings.user_agent}, timeout=60.0,
        follow_redirects=True,
    )  # fmt: skip
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return archive.read("ES.txt").decode("utf-8").splitlines()
