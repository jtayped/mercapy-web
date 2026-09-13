"""event derivation between two observations of one product in one warehouse.

PRODUCT.md: events compare observation days, not runs. the caller passes the
baseline (the version current at the end of the previous observation day) and
the latest data of today; both go through `scalars()` so the comparison never
depends on what the state table happened to cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from collector.payloads import JsonObject, Scalars, scalars

# events derived from a summary comparison. these are the ones a second run on
# the same day replaces; arrivals, disappearances and restorations are not.
DERIVED_TYPES = (
    "price_decrease",
    "price_increase",
    "official_reduction",
    "size_change",
    "rename",
    "category_move",
)


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    old_value: dict[str, Any]
    new_value: dict[str, Any]
    amount_delta: Decimal | None = None
    percent_delta: Decimal | None = None


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _price_event(old: Scalars, new: Scalars) -> Event | None:
    if (
        old.tracked_price is None
        or new.tracked_price is None
        or old.tracked_price_basis != new.tracked_price_basis
        or old.tracked_price == new.tracked_price
    ):
        return None
    amount = new.tracked_price - old.tracked_price
    percent = amount / old.tracked_price * Decimal("100") if old.tracked_price else None
    return Event(
        type="price_decrease" if amount < 0 else "price_increase",
        old_value={
            "tracked_price": str(old.tracked_price),
            "tracked_price_basis": old.tracked_price_basis,
        },
        new_value={
            "tracked_price": str(new.tracked_price),
            "tracked_price_basis": new.tracked_price_basis,
        },
        amount_delta=amount,
        percent_delta=percent,
    )


def _size_event(old: Scalars, new: Scalars) -> Event | None:
    # PRODUCT.md: variable-weight products change size every day by definition.
    if (
        old.approximate_size
        or new.approximate_size
        or old.unit_size is None
        or new.unit_size is None
        or old.unit_size == new.unit_size
        or old.size_format != new.size_format
    ):
        return None
    return Event(
        type="size_change",
        old_value={
            "unit_size": str(old.unit_size),
            "size_format": old.size_format,
            "unit_price": _text(old.unit_price),
            "bulk_price": _text(old.bulk_price),
        },
        new_value={
            "unit_size": str(new.unit_size),
            "size_format": new.size_format,
            "unit_price": _text(new.unit_price),
            "bulk_price": _text(new.bulk_price),
        },
    )


def derive_events(baseline: JsonObject, latest: JsonObject) -> list[Event]:
    old, new = scalars(baseline), scalars(latest)
    events: list[Event] = []
    price = _price_event(old, new)
    if price is not None:
        events.append(price)
    if not old.official_discount and new.official_discount:
        events.append(
            Event(
                type="official_reduction",
                old_value={"official_discount": False},
                new_value={"official_discount": True},
            )
        )
    size = _size_event(old, new)
    if size is not None:
        events.append(size)
    if old.name != new.name:
        events.append(
            Event(
                type="rename",
                old_value={"name": old.name},
                new_value={"name": new.name},
            )
        )
    if old.category_ids != new.category_ids:
        events.append(
            Event(
                type="category_move",
                old_value={"category_ids": old.category_ids},
                new_value={"category_ids": new.category_ids},
            )
        )
    return events
