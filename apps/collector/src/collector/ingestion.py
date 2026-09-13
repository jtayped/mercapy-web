"""one complete collection of one warehouse, and what it changes.

ARCHITECTURE.md: `crawl_run` is the trust boundary. a failed or unreconciled
run is recorded and changes nothing else. a successful one updates states,
closes and opens versions, and derives events against the previous
observation day inside one transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from mercapy import CatalogResult, ProductSummary

from collector.client import ClientFactory, open_client
from collector.config import Settings
from collector.consistency import check_price_consistency
from collector.db import Connection, Row, fetch_all, fetch_one, now_utc, observation_day
from collector.events import DERIVED_TYPES, Event, derive_events
from collector.payloads import (
    JsonObject,
    descriptive_change,
    scalars,
    summary_data,
    summary_fingerprint,
)
from collector.store import (
    enqueue_detail,
    insert_event,
    insert_version,
    mark_national_discontinuations,
    state_columns,
    sync_categories,
    upsert_product,
    version_data,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunResult:
    id: UUID
    warehouse_code: str
    status: str
    reported_count: int | None = None
    collected_count: int | None = None
    error: str = ""


@dataclass(slots=True)
class _Context:
    conn: Connection
    settings: Settings
    warehouse_code: str
    run_id: UUID
    observed_at: datetime
    observed_on: date
    states: dict[str, Row]
    warehouse_past_baseline: bool
    history_is_warm: bool


def _local_event(ctx: _Context, product_id: str, event_type: str) -> None:
    insert_event(
        ctx.conn,
        product_id=product_id,
        warehouse_code=ctx.warehouse_code,
        run_id=ctx.run_id,
        event=Event(type=event_type, old_value={}, new_value={}),
        observed_on=ctx.observed_on,
        occurred_at=ctx.observed_at,
    )


def _national_event(ctx: _Context, product_id: str, event_type: str) -> None:
    insert_event(
        ctx.conn,
        product_id=product_id,
        warehouse_code=None,
        run_id=ctx.run_id,
        event=Event(type=event_type, old_value={}, new_value={}),
        observed_on=ctx.observed_on,
        occurred_at=ctx.observed_at,
    )


def _create_state(
    ctx: _Context, summary: ProductSummary, data: JsonObject, digest: str, created: bool
) -> None:
    version_id = insert_version(ctx, summary.id, digest, data)
    columns = state_columns(data)
    ctx.conn.execute(
        """
        insert into product_state (product_id, warehouse_code, version_id, fingerprint,
            name, brand, category_ids, unit_price, previous_price, bulk_price,
            reference_price, tracked_price, tracked_price_basis, unit_size, size_format,
            reference_format, approximate_size, official_discount, published,
            first_seen_at, last_seen_at, observed_on)
        values (%(product)s, %(warehouse)s, %(version)s, %(fingerprint)s,
            %(name)s, %(brand)s, %(category_ids)s, %(unit_price)s, %(previous_price)s,
            %(bulk_price)s, %(reference_price)s, %(tracked_price)s,
            %(tracked_price_basis)s, %(unit_size)s, %(size_format)s,
            %(reference_format)s, %(approximate_size)s, %(official_discount)s,
            %(published)s, %(at)s, %(at)s, %(day)s)
        """,
        {
            **columns,
            "product": summary.id,
            "warehouse": ctx.warehouse_code,
            "version": version_id,
            "fingerprint": digest,
            "at": ctx.observed_at,
            "day": ctx.observed_on,
        },
    )
    if ctx.warehouse_past_baseline:
        _local_event(ctx, summary.id, "local_arrival")
        # a warehouse seen for the first time contributes products the tracker
        # simply never had coverage for; national arrivals wait until this
        # warehouse itself is past its baseline (COLLECTION.md).
        if created and ctx.history_is_warm:
            _national_event(ctx, summary.id, "national_arrival")
    enqueue_detail(ctx.conn, summary.id, ctx.warehouse_code, "first_seen")


def _update_state(
    ctx: _Context, state: Row, summary: ProductSummary, data: JsonObject, digest: str
) -> None:
    version_id = int(state["version_id"])
    baseline_id = state["baseline_version_id"]
    new_day = state["observed_on"] < ctx.observed_on
    if new_day:
        # the version open at the end of yesterday is what today compares to.
        baseline_id = version_id
    if state["fingerprint"] != digest:
        previous = version_data(ctx.conn, version_id)
        ctx.conn.execute(
            "update product_version set valid_to = %s where id = %s",
            (ctx.observed_at, version_id),
        )
        version_id = insert_version(ctx, summary.id, digest, data)
        if descriptive_change(previous, data):
            enqueue_detail(ctx.conn, summary.id, ctx.warehouse_code, "summary_change")
        if baseline_id is not None:
            baseline = (
                previous
                if baseline_id == state["version_id"]
                else version_data(ctx.conn, int(baseline_id))
            )
            if not new_day:
                # a second run today supersedes the first: the day's events are
                # always baseline -> last complete run (PRODUCT.md).
                ctx.conn.execute(
                    """
                    delete from product_event where product_id = %s
                      and warehouse_code = %s and observed_on = %s and type = any(%s)
                    """,
                    (
                        summary.id,
                        ctx.warehouse_code,
                        ctx.observed_on,
                        list(DERIVED_TYPES),
                    ),
                )
            for event in derive_events(baseline, data):
                insert_event(
                    ctx.conn,
                    product_id=summary.id,
                    warehouse_code=ctx.warehouse_code,
                    run_id=ctx.run_id,
                    event=event,
                    observed_on=ctx.observed_on,
                    occurred_at=ctx.observed_at,
                )
    ctx.conn.execute(
        """
        update product_state set version_id = %(version)s,
            baseline_version_id = %(baseline)s, fingerprint = %(fingerprint)s,
            name = %(name)s, brand = %(brand)s, category_ids = %(category_ids)s,
            unit_price = %(unit_price)s, previous_price = %(previous_price)s,
            bulk_price = %(bulk_price)s, reference_price = %(reference_price)s,
            tracked_price = %(tracked_price)s,
            tracked_price_basis = %(tracked_price_basis)s, unit_size = %(unit_size)s,
            size_format = %(size_format)s, reference_format = %(reference_format)s,
            approximate_size = %(approximate_size)s,
            official_discount = %(official_discount)s, published = %(published)s,
            last_seen_at = %(at)s, observed_on = %(day)s, absent_days = 0,
            last_absent_on = null, available = true, unavailable_since = null
        where product_id = %(product)s and warehouse_code = %(warehouse)s
        """,
        {
            **state_columns(data),
            "version": version_id,
            "baseline": baseline_id,
            "fingerprint": digest,
            "at": ctx.observed_at,
            "day": ctx.observed_on,
            "product": summary.id,
            "warehouse": ctx.warehouse_code,
        },
    )
    if not state["available"]:
        _local_event(ctx, summary.id, "restoration")


def _ingest(ctx: _Context, summary: ProductSummary) -> None:
    data = summary_data(summary)
    digest = summary_fingerprint(data)
    created, was_discontinued = upsert_product(ctx, summary)
    state = ctx.states.get(summary.id)
    if state is None:
        _create_state(ctx, summary, data, digest, created)
        categories_changed = True
    else:
        categories_changed = list(state["category_ids"]) != scalars(data).category_ids
        _update_state(ctx, state, summary, data, digest)
    if was_discontinued:
        _national_event(ctx, summary.id, "restoration")
    if categories_changed:
        sync_categories(ctx, summary)
    check_price_consistency(
        ctx.conn,
        price=summary.price,
        product_id=summary.id,
        warehouse_code=ctx.warehouse_code,
        run_id=ctx.run_id,
        now=ctx.observed_at,
    )


def _mark_missing(ctx: _Context, seen_ids: list[str]) -> None:
    # PRODUCT.md: "not available in this warehouse" needs two consecutive
    # absent days. a day counts once however many runs it had.
    absent = fetch_all(
        ctx.conn,
        """
        update product_state set absent_days = absent_days + 1, last_absent_on = %(day)s
        where warehouse_code = %(warehouse)s and available
          and (last_absent_on is null or last_absent_on < %(day)s)
          and product_id <> all(%(seen)s)
        returning product_id, absent_days
        """,
        {"day": ctx.observed_on, "warehouse": ctx.warehouse_code, "seen": seen_ids},
    )
    gone = [row["product_id"] for row in absent if row["absent_days"] >= 2]
    if not gone:
        return
    ctx.conn.execute(
        """
        update product_state set available = false, unavailable_since = %s
        where warehouse_code = %s and product_id = any(%s)
        """,
        (ctx.observed_at, ctx.warehouse_code, gone),
    )
    for product_id in gone:
        _local_event(ctx, product_id, "local_disappearance")


def _finish(
    conn: Connection,
    run_id: UUID,
    warehouse_code: str,
    status: str,
    error: str,
    **counts: Any,
) -> None:
    conn.execute(
        """
        update crawl_run set status = %(status)s, finished_at = now(),
            error = %(error)s, reported_count = %(reported)s,
            collected_count = %(collected)s, partition_count = %(partitions)s
        where id = %(id)s
        """,
        {
            "status": status,
            "error": error,
            "id": run_id,
            "reported": counts.get("reported"),
            "collected": counts.get("collected"),
            "partitions": counts.get("partitions"),
        },
    )
    conn.execute(
        "update warehouse set consecutive_failures = consecutive_failures + 1"
        " where code = %s",
        (warehouse_code,),
    )


def _fetch_catalog(
    settings: Settings, warehouse_code: str, client_factory: ClientFactory | None
) -> CatalogResult:
    if client_factory is None:
        with open_client(settings, warehouse_code) as client:
            return client.get_indexed_catalog()
    with client_factory(
        warehouse_code,
        language=settings.language,
        min_request_interval=settings.request_interval,
    ) as client:
        catalog: CatalogResult = client.get_indexed_catalog()
        return catalog


def collect_warehouse(
    conn: Connection,
    settings: Settings,
    warehouse_code: str,
    *,
    client_factory: ClientFactory | None = None,
    now: datetime | None = None,
) -> RunResult:
    code = warehouse_code.strip().lower()
    conn.execute(
        "insert into warehouse (code) values (%s) on conflict do nothing", (code,)
    )
    run = fetch_one(
        conn,
        "insert into crawl_run (warehouse_code, language) values (%s, %s) returning id",
        (code, settings.language),
    )
    assert run is not None  # noqa: S101
    run_id: UUID = run["id"]

    try:
        catalog = _fetch_catalog(settings, code, client_factory)
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        log.warning("%s: collection failed: %s", code, message)
        _finish(conn, run_id, code, "failed", message)
        return RunResult(run_id, code, "failed", error=message)

    counts = {
        "reported": catalog.reported_total_hits,
        "collected": len(catalog.products),
        "partitions": len(catalog.queried_category_ids),
    }
    if not catalog.reconciled:
        message = "deduplicated catalog count did not match the upstream hit count"
        log.warning(
            "%s: %s (%s/%s)", code, message, counts["collected"], counts["reported"]
        )
        _finish(conn, run_id, code, "degraded", message, **counts)
        return RunResult(
            run_id, code, "degraded", counts["reported"], counts["collected"], message
        )

    observed_at = now or now_utc()
    observed_on = observation_day(observed_at)
    with conn.transaction():
        # one collector per warehouse at a time; a second one waits, then sees
        # the states the first one wrote.
        conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (code,))
        warehouse = fetch_one(conn, "select * from warehouse where code = %s", (code,))
        assert warehouse is not None  # noqa: S101
        warm = fetch_one(
            conn,
            "select exists(select 1 from warehouse where baseline_days >= 2) as warm",
        )
        ctx = _Context(
            conn=conn,
            settings=settings,
            warehouse_code=code,
            run_id=run_id,
            observed_at=observed_at,
            observed_on=observed_on,
            states={
                row["product_id"]: row
                for row in fetch_all(
                    conn,
                    """
                    select product_id, version_id, baseline_version_id, fingerprint,
                        category_ids, observed_on, available
                    from product_state where warehouse_code = %s
                    """,
                    (code,),
                )
            },
            warehouse_past_baseline=warehouse["baseline_days"] >= 2,
            history_is_warm=bool(warm and warm["warm"]),
        )
        for summary in catalog.products:
            _ingest(ctx, summary)
        _mark_missing(ctx, [summary.id for summary in catalog.products])
        conn.execute(
            """
            update crawl_run set status = 'success', finished_at = %(at)s,
                observed_on = %(day)s, reported_count = %(reported)s,
                collected_count = %(collected)s, partition_count = %(partitions)s
            where id = %(id)s
            """,
            {"at": observed_at, "day": observed_on, "id": run_id, **counts},
        )
        conn.execute(
            """
            update warehouse set verified = true, last_success_at = %(at)s,
                consecutive_failures = 0,
                baseline_days = baseline_days
                    + case when last_observed_on is null or last_observed_on < %(day)s
                        then 1 else 0 end,
                last_observed_on = greatest(last_observed_on, %(day)s)
            where code = %(code)s
            """,
            {"at": observed_at, "day": observed_on, "code": code},
        )
    log.info(
        "%s: success, %s/%s products", code, counts["collected"], counts["reported"]
    )
    mark_national_discontinuations(conn, settings, now=observed_at, run_id=run_id)
    return RunResult(run_id, code, "success", counts["reported"], counts["collected"])
