from __future__ import annotations

from collector.config import Settings
from collector.db import Connection, fetch_all
from collector.discovery import (
    HISTORICAL_WAREHOUSES,
    discover_batch,
    import_postal_codes,
    resolve_postal_code,
    seed_historical_warehouses,
)
from collector.sweep import due_warehouses


def test_geonames_import_deduplicates_postal_codes(conn: Connection) -> None:
    lines = [
        "ES\t08001\tBarcelona\n",
        "ES\t08001\tBarcelona\n",
        "ES\t28001\tMadrid\n",
        "bad\n",
    ]
    assert import_postal_codes(conn, lines) == 2
    assert import_postal_codes(conn, lines) == 0
    rows = fetch_all(conn, "select postal_code, source from postal_code order by 1")
    assert [(row["postal_code"], row["source"]) for row in rows] == [
        ("08001", "geonames"),
        ("28001", "geonames"),
    ]


def test_resolution_records_the_mapping_and_creates_the_warehouse(
    conn: Connection, settings: Settings
) -> None:
    row = resolve_postal_code(
        conn, settings, "08001", source="visitor", resolver=lambda _: "bcn1"
    )
    assert row["warehouse_code"] == "bcn1"
    assert row["resolved_at"] is not None and row["last_error"] == ""
    assert fetch_all(conn, "select code, active, verified from warehouse") == [
        {"code": "bcn1", "active": True, "verified": False}
    ]

    def broken(_: str) -> str:
        raise ValueError("no header")

    row = resolve_postal_code(
        conn, settings, "99999", source="geonames", resolver=broken
    )
    assert row["warehouse_code"] is None
    assert row["last_error"] == "ValueError: no header"


def test_batches_pick_unchecked_codes_first(
    conn: Connection, settings: Settings
) -> None:
    import_postal_codes(conn, ["08001", "28001", "41001"])
    resolve_postal_code(
        conn, settings, "08001", source="geonames", resolver=lambda _: "bcn1"
    )
    rows = discover_batch(
        conn, settings, limit=2, max_age_days=30, resolver=lambda _: "mad1"
    )
    assert [row["postal_code"] for row in rows] == ["28001", "41001"]


def test_seed_is_inactive_until_a_postal_code_reaches_it(
    conn: Connection, settings: Settings
) -> None:
    assert seed_historical_warehouses(conn) == len(HISTORICAL_WAREHOUSES)
    assert seed_historical_warehouses(conn) == 0
    assert due_warehouses(conn, stale_hours=72) == []
    resolve_postal_code(
        conn, settings, "01001", source="geonames", resolver=lambda _: "4697"
    )
    assert due_warehouses(conn, stale_hours=72) == ["4697"]
