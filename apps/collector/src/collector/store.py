"""the writes every collection shares: products, categories, versions, the
state columns, events, the detail queue, and the national discontinuation rule."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from mercapy import ProductSummary
from psycopg.types.json import Jsonb

from collector.config import Settings
from collector.db import Connection, fetch_all, fetch_one, observation_day
from collector.events import Event
from collector.payloads import JsonObject, flatten_categories, scalars

if TYPE_CHECKING:
    from collector.ingestion import _Context

DETAIL_PRIORITY = {
    "first_seen": 0,
    "summary_change": 1,
    "audit": 2,
    "warehouse_divergence": 3,
    "sample": 4,
}


def insert_event(
    conn: Connection,
    *,
    product_id: str,
    warehouse_code: str | None,
    run_id: UUID | None,
    event: Event,
    observed_on: date,
    occurred_at: datetime,
) -> None:
    conn.execute(
        """
        insert into product_event (product_id, warehouse_code, crawl_run_id, type,
            observed_on, occurred_at, old_value, new_value, amount_delta, percent_delta)
        values (%(product)s, %(warehouse)s, %(run)s, %(type)s, %(day)s, %(at)s,
            %(old)s, %(new)s, %(amount)s, %(percent)s)
        """,
        {
            "product": product_id,
            "warehouse": warehouse_code,
            "run": run_id,
            "type": event.type,
            "day": observed_on,
            "at": occurred_at,
            "old": Jsonb(event.old_value),
            "new": Jsonb(event.new_value),
            "amount": event.amount_delta,
            "percent": event.percent_delta,
        },
    )


def enqueue_detail(
    conn: Connection, product_id: str, warehouse_code: str, reason: str
) -> None:
    conn.execute(
        """
        insert into detail_request (product_id, warehouse_code, reason, priority)
        values (%s, %s, %s, %s)
        on conflict (product_id, warehouse_code) do update
            set reason = excluded.reason, priority = excluded.priority
            where detail_request.priority > excluded.priority
        """,
        (product_id, warehouse_code, reason, DETAIL_PRIORITY[reason]),
    )


def insert_version(
    ctx: _Context, product_id: str, digest: str, data: JsonObject
) -> int:
    row = fetch_one(
        ctx.conn,
        """
        insert into product_version (product_id, warehouse_code, crawl_run_id,
            valid_from, fingerprint, data)
        values (%s, %s, %s, %s, %s, %s) returning id
        """,
        (
            product_id,
            ctx.warehouse_code,
            ctx.run_id,
            ctx.observed_at,
            digest,
            Jsonb(data),
        ),
    )
    assert row is not None  # noqa: S101 - returning always yields a row
    return int(row["id"])


def version_data(conn: Connection, version_id: int) -> JsonObject:
    row = fetch_one(
        conn, "select data from product_version where id = %s", (version_id,)
    )
    assert row is not None  # noqa: S101 - referenced by a foreign key
    data: JsonObject = row["data"]
    return data


def state_columns(data: JsonObject) -> dict[str, Any]:
    values = scalars(data)
    return {
        "name": values.name,
        "brand": values.brand,
        "category_ids": values.category_ids,
        "unit_price": values.unit_price,
        "previous_price": values.previous_price,
        "bulk_price": values.bulk_price,
        "reference_price": values.reference_price,
        "tracked_price": values.tracked_price,
        "tracked_price_basis": values.tracked_price_basis,
        "unit_size": values.unit_size,
        "size_format": values.size_format,
        "reference_format": values.reference_format,
        "approximate_size": values.approximate_size,
        "official_discount": values.official_discount,
        "published": values.published,
    }


def upsert_product(ctx: _Context, summary: ProductSummary) -> tuple[bool, bool]:
    """returns (created, was nationally discontinued)."""

    existing = fetch_one(
        ctx.conn,
        "select nationally_discontinued_at from product where id = %s",
        (summary.id,),
    )
    ctx.conn.execute(
        """
        insert into product (id, name, brand, slug, thumbnail_file, first_seen_at,
            last_seen_any_at)
        values (%(id)s, %(name)s, %(brand)s, %(slug)s, %(thumb)s, %(at)s, %(at)s)
        on conflict (id) do update set
            name = excluded.name, brand = excluded.brand, slug = excluded.slug,
            thumbnail_file = excluded.thumbnail_file,
            last_seen_any_at = excluded.last_seen_any_at,
            nationally_discontinued_at = null
        """,
        {
            "id": summary.id,
            "name": summary.name,
            "brand": summary.brand or "",
            "slug": summary.slug or "",
            "thumb": summary.thumbnail.file_name if summary.thumbnail else "",
            "at": ctx.observed_at,
        },
    )
    created = existing is None
    was_discontinued = (
        existing is not None and existing["nationally_discontinued_at"] is not None
    )
    return created, was_discontinued


def sync_categories(ctx: _Context, summary: ProductSummary) -> None:
    seen: list[str] = []
    for category, parent_id in flatten_categories(summary.categories):
        ctx.conn.execute(
            """
            insert into category (id, name, level, parent_id)
            values (%(id)s, %(name)s, %(level)s, %(parent)s)
            on conflict (id) do update set name = excluded.name,
                level = excluded.level, parent_id = excluded.parent_id
            """,
            {
                "id": category.id,
                "name": category.name,
                "level": category.level,
                "parent": parent_id,
            },
        )
        seen.append(category.id)
        ctx.conn.execute(
            """
            insert into product_category (product_id, warehouse_code, category_id,
                first_seen_at, last_seen_at)
            values (%(product)s, %(warehouse)s, %(category)s, %(at)s, %(at)s)
            on conflict (product_id, warehouse_code, category_id) do update
                set active = true, last_seen_at = excluded.last_seen_at
            """,
            {
                "product": summary.id,
                "warehouse": ctx.warehouse_code,
                "category": category.id,
                "at": ctx.observed_at,
            },
        )
    ctx.conn.execute(
        """
        update product_category set active = false
        where product_id = %s and warehouse_code = %s and active
          and category_id <> all(%s)
        """,
        (summary.id, ctx.warehouse_code, seen),
    )


def mark_national_discontinuations(
    conn: Connection, settings: Settings, *, now: datetime, run_id: UUID | None
) -> int:
    """PRODUCT.md: "no longer available anywhere" needs 14 days of absence in
    every active warehouse and data fresher than 72 hours in all of them."""

    freshness = now - timedelta(hours=settings.stale_hours)
    stale = fetch_one(
        conn,
        """
        select exists(
            select 1 from warehouse where active and verified
              and (last_success_at is null or last_success_at < %s)
        ) as stale
        """,
        (freshness,),
    )
    if stale and stale["stale"]:
        return 0
    cutoff = now - timedelta(days=settings.discontinued_days)
    with conn.transaction():
        rows = fetch_all(
            conn,
            """
            update product set nationally_discontinued_at = %(now)s
            where nationally_discontinued_at is null and last_seen_any_at <= %(cutoff)s
              and not exists (
                select 1 from product_state
                where product_state.product_id = product.id and product_state.available
              )
            returning id
            """,
            {"now": now, "cutoff": cutoff},
        )
        for row in rows:
            insert_event(
                conn,
                product_id=row["id"],
                warehouse_code=None,
                run_id=run_id,
                event=Event(
                    type="national_discontinuation", old_value={}, new_value={}
                ),
                observed_on=observation_day(now),
                occurred_at=now,
            )
    return len(rows)
