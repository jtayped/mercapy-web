from __future__ import annotations

from mercapy import NotFoundError, Product, ProductDetails

from collector.config import Settings
from collector.db import Connection, fetch_all, fetch_one
from collector.details import process_detail_queue, process_detail_request
from collector.ingestion import collect_warehouse

from .conftest import FakeClient, at, catalog, count, summary


def _requests(conn: Connection) -> list[dict[str, object]]:
    return fetch_all(
        conn, "select * from detail_request order by priority, warehouse_code"
    )


def _seed_three_warehouses(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    fake_client.catalog = catalog(summary("1.20"))
    for code in ("bcn1", "mad1", "vlc1"):
        collect_warehouse(conn, settings, code, client_factory=fake_client, now=at(1))


def test_detail_collection_starts_global_then_tracks_divergence(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    _seed_three_warehouses(conn, settings, fake_client)
    assert [row["reason"] for row in _requests(conn)] == ["first_seen"] * 3

    common = Product(
        id="100",
        name="Arròs rodó",
        ean="8410000000000",
        details=ProductDetails(origin="Espanya"),
    )
    different = Product(
        id="100",
        name="Arròs rodó",
        ean="8410000000000",
        details=ProductDetails(origin="Portugal"),
    )
    fake_client.products = {"bcn1": common, "mad1": different, "vlc1": common}

    first = fetch_one(
        conn, "select * from detail_request where warehouse_code = 'bcn1'"
    )
    assert first is not None
    # the other warehouses' own requests would double as audits; clear them so
    # the audit scheduling itself is what gets exercised.
    conn.execute("delete from detail_request where warehouse_code <> 'bcn1'")
    assert process_detail_request(
        conn, settings, first, client_factory=fake_client, now=at(1)
    )
    product = fetch_one(conn, "select * from product where id = '100'")
    assert product is not None
    assert product["detail_scope"] == "global"
    assert product["ean"] == "8410000000000"
    assert count(conn, "product_detail_version where warehouse_code is null") == 1
    assert [row["reason"] for row in _requests(conn)] == ["audit", "audit"]

    madrid = fetch_one(
        conn, "select * from detail_request where warehouse_code = 'mad1'"
    )
    assert madrid is not None
    assert process_detail_request(
        conn, settings, madrid, client_factory=fake_client, now=at(1)
    )
    product = fetch_one(conn, "select detail_scope from product where id = '100'")
    assert product is not None and product["detail_scope"] == "warehouse"
    assert count(conn, "product_detail_version where warehouse_code = 'mad1'") == 1
    assert count(conn, "product_event where type = 'detail_change'") == 1
    # the divergence schedules every other warehouse that still lacks its own record.
    assert {(row["warehouse_code"], row["reason"]) for row in _requests(conn)} == {
        ("vlc1", "audit"),
        ("bcn1", "warehouse_divergence"),
    }

    # the same madrid record again is not a change.
    conn.execute(
        "insert into detail_request (product_id, warehouse_code, reason, priority)"
        " values ('100', 'mad1', 'summary_change', 1)"
    )
    repeat = fetch_one(
        conn, "select * from detail_request where warehouse_code = 'mad1'"
    )
    assert repeat is not None
    assert process_detail_request(
        conn, settings, repeat, client_factory=fake_client, now=at(2)
    )
    assert count(conn, "product_event where type = 'detail_change'") == 1


def test_queue_order_errors_and_not_found(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    _seed_three_warehouses(conn, settings, fake_client)
    conn.execute(
        "update detail_request set reason = 'audit', priority = 2"
        " where warehouse_code = 'bcn1'"
    )

    class Failing(FakeClient):
        def get_product(self, product_id: str | int) -> Product:
            if self.warehouse == "mad1":
                raise RuntimeError("boom")
            if self.warehouse == "vlc1":
                raise NotFoundError("gone")
            return Product(id="100", name="Arròs rodó")

    stored, failed, dropped = process_detail_queue(
        conn, settings, limit=10, client_factory=Failing, now=at(1)
    )
    assert (stored, failed, dropped) == (1, 1, 1)
    remaining = _requests(conn)
    # mad1 waits for its retry; vlc1's request was dropped as not found and
    # then re-created as an audit by bcn1's successful canonical record.
    assert [
        (row["warehouse_code"], row["reason"], row["last_error"]) for row in remaining
    ] == [("mad1", "first_seen", "RuntimeError: boom"), ("vlc1", "audit", "")]
    assert remaining[0]["attempts"] == 1
    assert remaining[0]["not_before"] is not None
    # mad1 is not due yet; the new vlc1 audit is, and is dropped as not found.
    assert process_detail_queue(
        conn, settings, limit=10, client_factory=Failing, now=at(1)
    ) == (0, 0, 1)
    assert [row["warehouse_code"] for row in _requests(conn)] == ["mad1"]


def test_first_seen_requests_stop_after_enough_matching_audits(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    fake_client.catalog = catalog(summary("1.20"))
    codes = ("bcn1", "mad1", "vlc1", "svq1", "alc1")
    for code in codes:
        collect_warehouse(conn, settings, code, client_factory=fake_client, now=at(1))
    record = Product(
        id="100", name="Arròs rodó", details=ProductDetails(origin="Espanya")
    )
    fake_client.products = dict.fromkeys(codes, record)

    class Counting(FakeClient):
        calls = 0

        def get_product(self, product_id: str | int) -> Product:
            Counting.calls += 1
            return super().get_product(product_id)

    result = process_detail_queue(
        conn, settings, limit=10, client_factory=Counting, now=at(1)
    )
    # canonical record plus two matching audits are fetched; the other two are dropped.
    assert result == (3, 0, 2)
    assert Counting.calls == 3
    product = fetch_one(
        conn, "select detail_scope, detail_audits from product where id = '100'"
    )
    assert product == {"detail_scope": "global", "detail_audits": 2}
    assert _requests(conn) == []
