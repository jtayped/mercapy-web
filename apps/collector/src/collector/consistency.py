"""COLLECTION.md, prices: the upstream publishes two per-unit scales and the
check has to accept all the multipliers that make them agree with the basket
price. anomalies are recorded, never corrected."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from mercapy import Price
from psycopg.types.json import Jsonb

from collector.db import Connection


def expected_unit_price(price: Price) -> Decimal | None:
    """the basket price the per-unit figures imply, or None when the product
    has no comparable figures."""

    if (
        price.unit is None
        or (price.reference is None and price.bulk is None)
        or price.unit_size is None
        or price.size_format not in {"kg", "l", "ud"}
        or price.reference_format != price.size_format
        or price.approximate_size
    ):
        return None
    unit = price.unit
    normalized = price.reference if price.reference is not None else price.bulk
    assert normalized is not None  # noqa: S101 - narrowed by the check above
    multipliers = [price.unit_size]
    if price.drained_weight is not None:
        # a product sold in liquid publishes its reference price per drained
        # unit, which is smaller than the declared package size.
        multipliers.append(price.drained_weight)
    if price.reference_format == "ud":
        multipliers.append(Decimal("1"))
        if price.total_units is not None:
            multipliers.append(price.total_units)
    candidates = [normalized * multiplier for multiplier in multipliers]
    return min(candidates, key=lambda value: abs(value - unit))


def tolerance(price: Price) -> Decimal:
    # the reference price is truncated to three decimals upstream, so a small
    # reference over a large size carries a correspondingly large band.
    sizes = [price.unit_size or Decimal(0), price.total_units or Decimal(0)]
    rounding_band = max(sizes) * Decimal("0.0005")
    return max((price.unit or Decimal(0)) * Decimal("0.05"), rounding_band)


def check_price_consistency(
    conn: Connection,
    *,
    price: Price,
    product_id: str,
    warehouse_code: str,
    run_id: UUID,
    now: datetime,
) -> None:
    expected = expected_unit_price(price)
    consistent = (
        expected is None
        or price.unit is None
        or abs(expected - price.unit) <= tolerance(price)
    )
    if consistent:
        conn.execute(
            """
            update collection_issue set resolved_at = %(now)s
            where kind = 'price_consistency' and product_id = %(product)s
              and warehouse_code = %(warehouse)s and resolved_at is null
            """,
            {"now": now, "product": product_id, "warehouse": warehouse_code},
        )
        return
    conn.execute(
        """
        insert into collection_issue
            (kind, product_id, warehouse_code, crawl_run_id, data)
        select 'price_consistency', %(product)s, %(warehouse)s, %(run)s, %(data)s
        where not exists (
            select 1 from collection_issue
            where kind = 'price_consistency' and product_id = %(product)s
              and warehouse_code = %(warehouse)s and resolved_at is null
        )
        """,
        {
            "product": product_id,
            "warehouse": warehouse_code,
            "run": run_id,
            "data": Jsonb(
                {
                    "unit_price": str(price.unit),
                    "bulk_price": _text(price.bulk),
                    "reference_price": _text(price.reference),
                    "unit_size": str(price.unit_size),
                    "drained_weight": _text(price.drained_weight),
                    "total_units": _text(price.total_units),
                    "size_format": price.size_format,
                    "reference_format": price.reference_format,
                    "expected": str(expected),
                }
            ),
        },
    )


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
