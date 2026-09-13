"""STACK.md: the real boundary is python to postgres. the collector declares the
columns it writes; this compares them with the migrated database, and the
postgres enums with the contract's exported lists."""

from __future__ import annotations

import json

from collector.db import Connection, fetch_all

from .conftest import SCHEMA_DIR

WRITTEN_COLUMNS: dict[str, dict[str, str]] = {
    "warehouse": {
        "code": "text",
        "active": "boolean",
        "verified": "boolean",
        "baseline_days": "integer",
        "last_observed_on": "date",
        "last_success_at": "timestamp with time zone",
        "consecutive_failures": "integer",
    },
    "postal_code": {
        "postal_code": "text",
        "warehouse_code": "text",
        "source": "USER-DEFINED",
        "resolved_at": "timestamp with time zone",
        "last_checked_at": "timestamp with time zone",
        "last_error": "text",
    },
    "product": {
        "id": "text",
        "name": "text",
        "name_es": "text",
        "brand": "text",
        "ean": "text",
        "slug": "text",
        "thumbnail_file": "text",
        "first_seen_at": "timestamp with time zone",
        "last_seen_any_at": "timestamp with time zone",
        "nationally_discontinued_at": "timestamp with time zone",
        "detail_scope": "USER-DEFINED",
        "detail_audits": "smallint",
    },
    "category": {
        "id": "text",
        "name": "text",
        "level": "smallint",
        "parent_id": "text",
    },
    "crawl_run": {
        "id": "uuid",
        "warehouse_code": "text",
        "finished_at": "timestamp with time zone",
        "status": "USER-DEFINED",
        "language": "text",
        "observed_on": "date",
        "reported_count": "integer",
        "collected_count": "integer",
        "partition_count": "integer",
        "error": "text",
    },
    "product_version": {
        "id": "bigint",
        "product_id": "text",
        "warehouse_code": "text",
        "crawl_run_id": "uuid",
        "valid_from": "timestamp with time zone",
        "valid_to": "timestamp with time zone",
        "fingerprint": "text",
        "data": "jsonb",
    },
    "product_state": {
        "product_id": "text",
        "warehouse_code": "text",
        "version_id": "bigint",
        "baseline_version_id": "bigint",
        "fingerprint": "text",
        "name": "text",
        "brand": "text",
        "category_ids": "ARRAY",
        "unit_price": "numeric",
        "previous_price": "numeric",
        "bulk_price": "numeric",
        "reference_price": "numeric",
        "tracked_price": "numeric",
        "tracked_price_basis": "USER-DEFINED",
        "unit_size": "numeric",
        "size_format": "text",
        "reference_format": "text",
        "approximate_size": "boolean",
        "official_discount": "boolean",
        "published": "boolean",
        "first_seen_at": "timestamp with time zone",
        "last_seen_at": "timestamp with time zone",
        "observed_on": "date",
        "absent_days": "smallint",
        "last_absent_on": "date",
        "available": "boolean",
        "unavailable_since": "timestamp with time zone",
    },
    "product_category": {
        "product_id": "text",
        "warehouse_code": "text",
        "category_id": "text",
        "active": "boolean",
        "first_seen_at": "timestamp with time zone",
        "last_seen_at": "timestamp with time zone",
    },
    "product_detail_version": {
        "id": "bigint",
        "product_id": "text",
        "warehouse_code": "text",
        "valid_from": "timestamp with time zone",
        "valid_to": "timestamp with time zone",
        "fingerprint": "text",
        "data": "jsonb",
    },
    "product_event": {
        "product_id": "text",
        "warehouse_code": "text",
        "crawl_run_id": "uuid",
        "type": "USER-DEFINED",
        "observed_on": "date",
        "occurred_at": "timestamp with time zone",
        "old_value": "jsonb",
        "new_value": "jsonb",
        "amount_delta": "numeric",
        "percent_delta": "numeric",
    },
    "detail_request": {
        "product_id": "text",
        "warehouse_code": "text",
        "reason": "USER-DEFINED",
        "priority": "smallint",
        "attempts": "smallint",
        "last_error": "text",
        "not_before": "timestamp with time zone",
    },
    "collection_issue": {
        "kind": "USER-DEFINED",
        "product_id": "text",
        "warehouse_code": "text",
        "crawl_run_id": "uuid",
        "data": "jsonb",
        "resolved_at": "timestamp with time zone",
    },
}


def test_every_written_column_exists_with_the_expected_type(conn: Connection) -> None:
    rows = fetch_all(
        conn,
        """
        select table_name, column_name, data_type from information_schema.columns
        where table_schema = 'public'
        """,
    )
    actual = {(row["table_name"], row["column_name"]): row["data_type"] for row in rows}
    missing = [
        (table, column, expected, actual.get((table, column)))
        for table, columns in WRITTEN_COLUMNS.items()
        for column, expected in columns.items()
        if actual.get((table, column)) != expected
    ]
    assert missing == []


def test_postgres_enums_match_the_contract(conn: Connection) -> None:
    contract = json.loads((SCHEMA_DIR / "enums.json").read_text())["properties"]
    rows = fetch_all(
        conn,
        """
        select t.typname as name,
            array_agg(e.enumlabel order by e.enumsortorder) as labels
        from pg_type t join pg_enum e on e.enumtypid = t.oid
        group by t.typname
        """,
    )
    actual = {row["name"]: list(row["labels"]) for row in rows}
    expected = {name: schema["enum"] for name, schema in contract.items()}
    assert actual == expected
