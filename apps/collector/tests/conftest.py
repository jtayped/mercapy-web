from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest
from mercapy import CatalogResult, Price, Product, ProductSummary

from collector.config import Settings
from collector.db import Connection, connect
from collector.migrations import apply_migrations

DEFAULT_URL = "postgresql://mercapy:mercapy-dev@localhost:5435/mercapy_test"
MIGRATIONS = Path(__file__).resolve().parents[3] / "packages" / "db" / "drizzle"
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "packages" / "contract" / "schema"

TABLES = (
    "collection_issue",
    "detail_request",
    "product_event",
    "product_detail_version",
    "product_category",
    "product_state",
    "product_version",
    "crawl_run",
    "category",
    "product",
    "postal_code",
    "warehouse",
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        database_url=os.environ.get("TEST_DATABASE_URL", DEFAULT_URL),
        request_interval=0,
        migrations_dir=MIGRATIONS,
    )


@pytest.fixture(scope="session")
def session_conn(settings: Settings) -> Iterator[Connection]:
    with connect(settings.database_url) as conn:
        conn.execute("drop schema if exists public cascade")
        conn.execute("drop schema if exists drizzle cascade")
        conn.execute("create schema public")
        apply_migrations(conn, settings.migrations_dir)
        yield conn


@pytest.fixture
def conn(session_conn: Connection) -> Connection:
    session_conn.execute(f"truncate {', '.join(TABLES)} restart identity cascade")
    return session_conn


def count(conn: Connection, source: str) -> int:
    """rows in a table, or matching `table where ...`."""

    row = conn.execute(f"select count(*) as n from {source}").fetchone()
    assert row is not None
    return int(row["n"])


def at(day: int, hour: int = 10) -> datetime:
    """an instant on 2026-09-<day> at <hour>:00 in Europe/Madrid (utc+2)."""

    return datetime(2026, 9, day, hour - 2, tzinfo=UTC)


class FakeClient:
    """a mercapy client whose answers are set on the class between calls."""

    catalog: ClassVar[CatalogResult] = CatalogResult((), 0, (), True)
    error: ClassVar[Exception | None] = None
    products: ClassVar[dict[str, Product]] = {}

    def __init__(self, warehouse: str, **kwargs: Any) -> None:
        self.warehouse = warehouse

    def __enter__(self) -> FakeClient:
        if self.error:
            raise self.error
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def get_indexed_catalog(self) -> CatalogResult:
        return self.catalog

    def get_product(self, product_id: str | int) -> Product:
        return self.products[self.warehouse]


@pytest.fixture
def fake_client() -> Iterator[type[FakeClient]]:
    FakeClient.catalog = CatalogResult((), 0, (), True)
    FakeClient.error = None
    FakeClient.products = {}
    yield FakeClient


def catalog(*products: ProductSummary) -> CatalogResult:
    return CatalogResult(products, len(products), ("1",), True)


def summary(
    price: str,
    *,
    product_id: str = "100",
    name: str = "Arròs rodó",
    size: str = "1",
    size_format: str = "kg",
    discounted: bool = False,
    reference: str | None = None,
    approximate: bool = False,
) -> ProductSummary:
    unit = Decimal(price)
    return ProductSummary(
        id=product_id,
        name=name,
        price=Price(
            unit=unit,
            bulk=unit / Decimal(size),
            reference=Decimal(reference) if reference else None,
            unit_size=Decimal(size),
            size_format=size_format,
            reference_format=size_format,
            is_discounted=discounted,
            approximate_size=approximate,
        ),
    )
