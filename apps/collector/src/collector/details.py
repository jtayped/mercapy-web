"""the deferred detail queue (COLLECTION.md, adaptive details).

the first warehouse that shows a product supplies the canonical record. two
audits in other warehouses follow; a difference makes the record warehouse
specific and schedules the remaining variants.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from mercapy import NotFoundError, Product
from psycopg.types.json import Jsonb

from collector.client import ClientFactory, open_client
from collector.config import Settings
from collector.db import Connection, Row, fetch_all, fetch_one, now_utc, observation_day
from collector.events import Event
from collector.payloads import JsonObject, detail_data, fingerprint
from collector.store import enqueue_detail, insert_event

log = logging.getLogger(__name__)


def _fetch_detail(
    settings: Settings,
    warehouse_code: str,
    product_id: str,
    client_factory: ClientFactory | None,
) -> Product:
    if client_factory is None:
        with open_client(settings, warehouse_code) as client:
            return client.get_product(product_id)
    with client_factory(
        warehouse_code,
        language=settings.language,
        min_request_interval=settings.request_interval,
    ) as client:
        product: Product = client.get_product(product_id)
        return product


def _open_version(
    conn: Connection, product_id: str, warehouse_code: str | None
) -> Row | None:
    return fetch_one(
        conn,
        """
        select id, fingerprint, data from product_detail_version
        where product_id = %s and warehouse_code is not distinct from %s
          and valid_to is null
        """,
        (product_id, warehouse_code),
    )


def _detail_event(
    conn: Connection,
    product_id: str,
    warehouse_code: str,
    old: JsonObject,
    new: JsonObject,
    now: datetime,
) -> None:
    insert_event(
        conn,
        product_id=product_id,
        warehouse_code=warehouse_code,
        run_id=None,
        event=Event(
            type="detail_change", old_value={"detail": old}, new_value={"detail": new}
        ),
        observed_on=observation_day(now),
        occurred_at=now,
    )


def _store(
    conn: Connection,
    request: Row,
    detail: Product,
    now: datetime,
) -> None:
    product_id, warehouse_code = request["product_id"], request["warehouse_code"]
    payload = detail_data(detail)
    digest = fingerprint(payload)
    product = fetch_one(
        conn, "select detail_scope from product where id = %s", (product_id,)
    )
    assert product is not None  # noqa: S101 - the request references it
    scope: str = product["detail_scope"]
    existing_global = _open_version(conn, product_id, None)
    initial_collection = existing_global is None and scope != "warehouse"

    target: str | None = None
    diverged = False
    if scope == "warehouse":
        target = warehouse_code
    else:
        scope = "global"
        if existing_global is not None and existing_global["fingerprint"] != digest:
            scope = "warehouse"
            target = warehouse_code
            diverged = True

    current = _open_version(conn, product_id, target)
    changed = current is None or current["fingerprint"] != digest
    if scope == "global" and existing_global is not None and not changed:
        conn.execute(
            "update product set detail_audits = detail_audits + 1 where id = %s",
            (product_id,),
        )
    if diverged and existing_global is not None:
        for row in fetch_all(
            conn,
            "select warehouse_code from product_state"
            " where product_id = %s and available",
            (product_id,),
        ):
            enqueue_detail(
                conn, product_id, row["warehouse_code"], "warehouse_divergence"
            )
        _detail_event(
            conn, product_id, warehouse_code, existing_global["data"], payload, now
        )
    elif scope == "warehouse" and current is not None and changed:
        _detail_event(conn, product_id, warehouse_code, current["data"], payload, now)

    if changed:
        if current is not None:
            conn.execute(
                "update product_detail_version set valid_to = %s where id = %s",
                (now, current["id"]),
            )
        conn.execute(
            """
            insert into product_detail_version (product_id, warehouse_code, valid_from,
                fingerprint, data)
            values (%s, %s, %s, %s, %s)
            """,
            (product_id, target, now, digest, Jsonb(payload)),
        )
    conn.execute(
        """
        update product set detail_scope = %s,
            ean = coalesce(nullif(%s, ''), ean)
        where id = %s
        """,
        (scope, detail.ean or "", product_id),
    )
    conn.execute(
        "delete from detail_request where product_id = %s and warehouse_code = %s",
        (product_id, warehouse_code),
    )
    if initial_collection:
        for row in fetch_all(
            conn,
            """
            select warehouse_code from product_state
            where product_id = %s and available and warehouse_code <> %s
            order by warehouse_code limit 2
            """,
            (product_id, warehouse_code),
        ):
            enqueue_detail(conn, product_id, row["warehouse_code"], "audit")


def _audited_enough(conn: Connection, settings: Settings, request: Row) -> bool:
    """a first-seen or audit request for a product whose global record has
    already been confirmed in enough other warehouses has nothing to add."""

    if request["reason"] not in {"first_seen", "audit"}:
        return False
    row = fetch_one(
        conn,
        "select detail_scope, detail_audits from product where id = %s",
        (request["product_id"],),
    )
    return (
        row is not None
        and row["detail_scope"] == "global"
        and row["detail_audits"] >= settings.detail_audits
    )


def process_detail_request(
    conn: Connection,
    settings: Settings,
    request: Row,
    *,
    client_factory: ClientFactory | None = None,
    now: datetime | None = None,
) -> bool | None:
    """True when a record was stored, False on a failure that will be retried,
    None when the request was dropped without a fetch."""

    product_id, warehouse_code = request["product_id"], request["warehouse_code"]
    if _audited_enough(conn, settings, request):
        conn.execute(
            "delete from detail_request where product_id = %s and warehouse_code = %s",
            (product_id, warehouse_code),
        )
        return None
    try:
        detail = _fetch_detail(settings, warehouse_code, product_id, client_factory)
    except NotFoundError:
        # the product left this warehouse between the catalog and now. the next
        # catalog collection records that; the request has nothing to fetch.
        conn.execute(
            "delete from detail_request where product_id = %s and warehouse_code = %s",
            (product_id, warehouse_code),
        )
        return None
    except Exception as error:
        attempts = int(request["attempts"]) + 1
        conn.execute(
            """
            update detail_request set attempts = %s, last_error = %s, not_before = %s
            where product_id = %s and warehouse_code = %s
            """,
            (
                attempts,
                f"{type(error).__name__}: {error}",
                (now or now_utc()) + timedelta(hours=min(24, 2 ** min(attempts, 5))),
                product_id,
                warehouse_code,
            ),
        )
        return False
    with conn.transaction():
        _store(conn, request, detail, now or now_utc())
    return True


def process_detail_queue(
    conn: Connection,
    settings: Settings,
    *,
    limit: int,
    client_factory: ClientFactory | None = None,
    now: datetime | None = None,
) -> tuple[int, int, int]:
    """returns (stored, failed, dropped). the queue order is the priority
    column: new products, descriptive changes, audits, divergences, the sample.
    dropped requests cost no request, so `limit` bounds the http traffic."""

    current = now or now_utc()
    requests = fetch_all(
        conn,
        """
        select product_id, warehouse_code, reason, attempts from detail_request
        where not_before is null or not_before <= %s
        order by priority, created_at limit %s
        """,
        (current, limit),
    )
    results = [
        process_detail_request(
            conn, settings, request, client_factory=client_factory, now=now
        )
        for request in requests
    ]
    stored = sum(result is True for result in results)
    dropped = sum(result is None for result in results)
    return stored, len(results) - stored - dropped, dropped


def enqueue_sample(conn: Connection, *, limit: int, max_age_days: int = 30) -> int:
    """the monthly sample: refetch the oldest current detail records so a change
    the summary cannot show (ingredients, origin) is still seen eventually."""

    rows = fetch_all(
        conn,
        """
        select v.product_id,
            coalesce(v.warehouse_code, s.warehouse_code) as warehouse_code
        from product_detail_version v
        join product_state s on s.product_id = v.product_id and s.available
          and (v.warehouse_code is null or v.warehouse_code = s.warehouse_code)
        where v.valid_to is null and v.valid_from < now() - make_interval(days => %s)
          and not exists (
            select 1 from detail_request r
            where r.product_id = v.product_id and r.warehouse_code = s.warehouse_code
          )
        order by v.valid_from limit %s
        """,
        (max_age_days, limit),
    )
    for row in rows:
        enqueue_detail(conn, row["product_id"], row["warehouse_code"], "sample")
    return len(rows)
