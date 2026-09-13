from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import cast

from mercapy import CatalogResult, Category, Price, ProductSummary

from collector.config import Settings
from collector.db import Connection, fetch_all, fetch_one
from collector.ingestion import collect_warehouse
from collector.store import mark_national_discontinuations

from .conftest import FakeClient, at, catalog, count, summary


def _events(conn: Connection, event_type: str) -> list[dict[str, object]]:
    return fetch_all(
        conn, "select * from product_event where type = %s order by id", (event_type,)
    )


def _state(conn: Connection, product_id: str = "100") -> dict[str, object]:
    row = fetch_one(
        conn, "select * from product_state where product_id = %s", (product_id,)
    )
    assert row is not None
    return row


def test_versions_changes_and_derives_events_between_days(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    fake_client.catalog = catalog(summary("1.20"))
    first = collect_warehouse(
        conn, settings, "bcn1", client_factory=fake_client, now=at(1)
    )
    assert first.status == "success"
    assert count(conn, "product_version") == 1
    assert _state(conn)["baseline_version_id"] is None

    fake_client.catalog = catalog(summary("1.00", name="Arròs rodó Hacendado"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2))
    assert count(conn, "product_version") == 2
    assert count(conn, "product_version where valid_to is null") == 1
    decreases = _events(conn, "price_decrease")
    assert len(decreases) == 1
    assert decreases[0]["old_value"] == {
        "tracked_price": "1.20",
        "tracked_price_basis": "unit",
    }
    assert decreases[0]["amount_delta"] == Decimal("-0.2000")
    assert len(_events(conn, "rename")) == 1
    state = _state(conn)
    assert state["tracked_price"] == Decimal("1.0000")
    assert state["baseline_version_id"] == 1
    assert state["version_id"] == 2


def test_a_second_run_on_the_same_day_replaces_the_days_events(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    fake_client.catalog = catalog(summary("1.20"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(1))
    fake_client.catalog = catalog(summary("1.00"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2, 9))
    assert len(_events(conn, "price_decrease")) == 1

    # back to the baseline price the same afternoon: no decrease, no increase.
    fake_client.catalog = catalog(summary("1.20"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2, 17))
    assert _events(conn, "price_decrease") == []
    assert _events(conn, "price_increase") == []
    # versions still record every run.
    assert count(conn, "product_version") == 3


def test_disappearance_needs_two_absent_days_not_two_runs(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    fake_client.catalog = catalog(summary("1.20"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(1))
    fake_client.catalog = catalog()
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2, 9))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2, 17))
    state = _state(conn)
    assert state["available"] and state["absent_days"] == 1

    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(3))
    state = _state(conn)
    assert not state["available"] and state["absent_days"] == 2
    assert len(_events(conn, "local_disappearance")) == 1

    fake_client.catalog = catalog(summary("1.20"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(4))
    assert _state(conn)["available"]
    assert len(_events(conn, "restoration")) == 1


def test_failed_and_degraded_runs_change_nothing(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    fake_client.catalog = catalog(summary("1.20"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(1))

    fake_client.error = RuntimeError("upstream unavailable")
    failed = collect_warehouse(
        conn, settings, "bcn1", client_factory=fake_client, now=at(2)
    )
    fake_client.error = None
    assert failed.status == "failed"

    fake_client.catalog = CatalogResult((), 2, ("1",), False)
    degraded = collect_warehouse(
        conn, settings, "bcn1", client_factory=fake_client, now=at(3)
    )
    assert degraded.status == "degraded"

    assert _state(conn)["absent_days"] == 0
    warehouse = fetch_one(conn, "select * from warehouse where code = 'bcn1'")
    assert warehouse is not None
    assert warehouse["consecutive_failures"] == 2
    assert warehouse["baseline_days"] == 1


def test_baseline_days_count_days_and_gate_arrivals(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    fake_client.catalog = catalog(summary("1.20"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(1, 9))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(1, 17))
    fake_client.catalog = catalog(
        summary("1.20"), summary("2", product_id="200", name="Oli")
    )
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2))
    # one observation day so far: still a baseline, no arrival events.
    assert _events(conn, "local_arrival") == []

    fake_client.catalog = catalog(
        summary("1.20"),
        summary("2", product_id="200", name="Oli"),
        summary("3", product_id="300", name="Sal"),
    )
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(3))
    assert [event["product_id"] for event in _events(conn, "local_arrival")] == ["300"]
    assert [event["product_id"] for event in _events(conn, "national_arrival")] == [
        "300"
    ]

    # a new warehouse's first catalog contributes coverage, not novelties.
    fake_client.catalog = catalog(
        summary("1.20"), summary("9", product_id="900", name="Local")
    )
    collect_warehouse(conn, settings, "svq1", client_factory=fake_client, now=at(3))
    assert len(_events(conn, "national_arrival")) == 1
    assert len(_events(conn, "local_arrival")) == 1


def test_variable_weight_tracks_reference_price_and_skips_size_changes(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    hake = summary(
        "12.77",
        product_id="7",
        name="Lluç",
        size="1.11",
        reference="11.50",
        approximate=True,
    )
    fake_client.catalog = catalog(hake)
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(1))
    state = _state(conn, "7")
    assert state["tracked_price"] == Decimal("11.5000")
    assert state["tracked_price_basis"] == "reference"

    # a different cut at the same price per kilo is not a price event.
    fake_client.catalog = catalog(
        summary(
            "17.14",
            product_id="7",
            name="Lluç",
            size="1.49",
            reference="11.50",
            approximate=True,
        )
    )
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2))
    assert _events(conn, "price_increase") == []
    assert _events(conn, "size_change") == []


def test_size_change_at_the_same_shelf_price(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    fake_client.catalog = catalog(summary("2.00", size="0.5"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(1))
    fake_client.catalog = catalog(summary("2.00", size="0.4"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2))
    events = _events(conn, "size_change")
    assert len(events) == 1
    old_value = cast(dict[str, str], events[0]["old_value"])
    new_value = cast(dict[str, str], events[0]["new_value"])
    assert old_value["unit_size"] == "0.5"
    assert Decimal(new_value["bulk_price"]) == 5
    assert _events(conn, "price_increase") == []


def test_official_reduction_and_category_moves(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    def product(discounted: bool, category: str) -> ProductSummary:
        return ProductSummary(
            id="100",
            name="Arròs",
            price=Price(unit=Decimal("1"), is_discounted=discounted),
            categories=(Category(id=category, name=f"cat {category}", level=1),),
        )

    fake_client.catalog = catalog(product(False, "1"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(1))
    fake_client.catalog = catalog(product(True, "2"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2))
    assert len(_events(conn, "official_reduction")) == 1
    assert len(_events(conn, "category_move")) == 1
    memberships = fetch_all(
        conn, "select category_id, active from product_category order by category_id"
    )
    assert [(row["category_id"], row["active"]) for row in memberships] == [
        ("1", False),
        ("2", True),
    ]


def test_price_consistency_issues(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    candles = ProductSummary(
        id="200",
        name="Espelmes",
        price=Price(
            unit=Decimal("1.40"),
            bulk=Decimal("0.14"),
            reference=Decimal("0.140"),
            unit_size=Decimal("1"),
            total_units=Decimal("10"),
            size_format="ud",
            reference_format="ud",
        ),
    )
    mozzarella = ProductSummary(
        id="300",
        name="Mozzarella",
        price=Price(
            unit=Decimal("0.90"),
            bulk=Decimal("3.60"),
            reference=Decimal("7.200"),
            unit_size=Decimal("0.25"),
            drained_weight=Decimal("0.125"),
            size_format="kg",
            reference_format="kg",
        ),
    )
    toothpicks = ProductSummary(
        id="301",
        name="Escuradents",
        price=Price(
            unit=Decimal("1.25"),
            bulk=Decimal("0.00"),
            reference=Decimal("0.003"),
            unit_size=Decimal("500"),
            size_format="ud",
            reference_format="ud",
        ),
    )
    wrong = ProductSummary(
        id="201",
        name="Incoherent",
        price=Price(
            unit=Decimal("10"),
            bulk=Decimal("1"),
            reference=Decimal("1"),
            unit_size=Decimal("2"),
            size_format="kg",
            reference_format="kg",
        ),
    )
    fake_client.catalog = catalog(candles, mozzarella, toothpicks, wrong)
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(1))
    issues = fetch_all(conn, "select * from collection_issue where resolved_at is null")
    assert [issue["product_id"] for issue in issues] == ["201"]
    assert issues[0]["data"]["expected"] == "2"

    fake_client.catalog = catalog(candles, mozzarella, toothpicks)
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2))
    # the issue stays open until the product shows a coherent price again.
    assert count(conn, "collection_issue where resolved_at is null") == 1


def test_national_discontinuation_needs_fresh_verified_warehouses(
    conn: Connection, settings: Settings, fake_client: type[FakeClient]
) -> None:
    fake_client.catalog = catalog(summary("1.20"))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(1))
    fake_client.catalog = catalog()
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(2))
    collect_warehouse(conn, settings, "bcn1", client_factory=fake_client, now=at(3))
    assert not _state(conn)["available"]

    # an unverified candidate warehouse never blocks the rule.
    conn.execute(
        "insert into warehouse (code, active, verified) values ('4115', false, false)"
    )
    later = at(3) + timedelta(days=13)
    assert mark_national_discontinuations(conn, settings, now=later, run_id=None) == 0
    # 14 days after the last sighting, but bcn1's data is stale by then.
    later = at(1) + timedelta(days=14, hours=1)
    assert mark_national_discontinuations(conn, settings, now=later, run_id=None) == 0
    conn.execute(
        "update warehouse set last_success_at = %s where code = 'bcn1'", (later,)
    )
    assert mark_national_discontinuations(conn, settings, now=later, run_id=None) == 1
    assert len(_events(conn, "national_discontinuation")) == 1

    fake_client.catalog = catalog(summary("1.20"))
    collect_warehouse(
        conn,
        settings,
        "bcn1",
        client_factory=fake_client,
        now=later + timedelta(days=1),
    )
    national = [
        event
        for event in _events(conn, "restoration")
        if event["warehouse_code"] is None
    ]
    assert len(national) == 1
