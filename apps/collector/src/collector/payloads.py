"""the json the collector writes, shaped exactly as packages/contract declares.

the tests validate these dictionaries against the exported json schema, which
is the whole python/typescript boundary. decimals are strings on both sides.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from mercapy import Category, Price, Product, ProductSummary

JsonObject = dict[str, Any]


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _parse_decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def fingerprint(payload: JsonObject) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


# the summary keys a version is *not* opened for. everything is stored; these
# change without meaning anything and would open a version for nothing.
UNCOMPARED_KEYS = frozenset(
    {"share_url", "availability_limit", "unavailable_from", "unavailable_weekdays"}
)
UNCOMPARED_PRICE_KEYS = frozenset({"minimum_amount", "increment_amount"})
COMPARED_CATEGORY_KEYS = ("id", "name", "level", "parent_id")


def comparable(data: JsonObject) -> JsonObject:
    """the subset of a summary that the version fingerprint covers."""

    subset = {key: value for key, value in data.items() if key not in UNCOMPARED_KEYS}
    subset["price"] = {
        key: value
        for key, value in data["price"].items()
        if key not in UNCOMPARED_PRICE_KEYS
    }
    subset["categories"] = [
        {key: category[key] for key in COMPARED_CATEGORY_KEYS}
        for category in data["categories"]
    ]
    return subset


def summary_fingerprint(data: JsonObject) -> str:
    return fingerprint(comparable(data))


def flatten_categories(
    categories: tuple[Category, ...],
) -> list[tuple[Category, str | None]]:
    """depth-first list of (category, parent id), top level first."""

    result: list[tuple[Category, str | None]] = []

    def visit(category: Category, parent_id: str | None) -> None:
        result.append((category, parent_id))
        for child in category.children:
            visit(child, category.id)

    for category in categories:
        visit(category, None)
    return result


def price_data(price: Price) -> JsonObject:
    return {
        "unit": _decimal(price.unit),
        "previous": _decimal(price.previous),
        "bulk": _decimal(price.bulk),
        "reference": _decimal(price.reference),
        "tax_percentage": _decimal(price.tax_percentage),
        "unit_size": _decimal(price.unit_size),
        "pack_size": _decimal(price.pack_size),
        "total_units": _decimal(price.total_units),
        "drained_weight": _decimal(price.drained_weight),
        "minimum_amount": _decimal(price.minimum_amount),
        "increment_amount": _decimal(price.increment_amount),
        "unit_name": price.unit_name,
        "size_format": price.size_format,
        "reference_format": price.reference_format,
        "is_discounted": price.is_discounted,
        "is_new": price.is_new,
        "is_pack": price.is_pack,
        "approximate_size": price.approximate_size,
    }


def summary_data(summary: ProductSummary) -> JsonObject:
    return {
        "id": summary.id,
        "name": summary.name,
        "slug": summary.slug,
        "brand": summary.brand,
        "packaging": summary.packaging,
        "main_feature": summary.main_feature,
        "share_url": summary.share_url,
        "thumbnail": summary.thumbnail.file_name if summary.thumbnail else None,
        "price": price_data(summary.price),
        "published": summary.availability.published,
        "status": summary.availability.status,
        "availability_limit": _decimal(summary.availability.limit),
        "unavailable_from": summary.availability.unavailable_from,
        "unavailable_weekdays": list(summary.availability.unavailable_weekdays),
        "categories": [
            {
                "id": category.id,
                "name": category.name,
                "level": category.level,
                "parent_id": parent_id,
                "order": category.order,
                "layout": category.layout,
                "published": category.published,
                "is_extended": category.is_extended,
                "image_url": category.image_url,
                "subtitle": category.subtitle,
            }
            for category, parent_id in flatten_categories(summary.categories)
        ],
        "requires_age_check": summary.requires_age_check,
        "is_water": summary.is_water,
        "is_new_arrival": summary.is_new_arrival,
    }


def detail_data(product: Product) -> JsonObject:
    # POLICY.md: facts only. `description` is marketing copy and stays out.
    details = product.details
    return {
        "id": product.id,
        "name": product.name,
        "ean": product.ean,
        "slug": product.slug,
        "brand": product.brand,
        "packaging": product.packaging,
        "main_feature": product.main_feature,
        "photos": [photo.file_name for photo in product.photos],
        "legal_name": details.legal_name,
        "origin": details.origin,
        "suppliers": list(details.suppliers),
        "counter_info": details.counter_info,
        "danger_mentions": details.danger_mentions,
        "mandatory_mentions": details.mandatory_mentions,
        "production_variant": details.production_variant,
        "usage_instructions": details.usage_instructions,
        "storage_instructions": details.storage_instructions,
        "alcohol_by_volume": _decimal(details.alcohol_by_volume),
        "prepared_by_mercadona": details.prepared_by_mercadona,
        "allergens": product.nutrition.allergens,
        "ingredients": product.nutrition.ingredients,
        "is_bulk": product.is_bulk,
        "is_variable_weight": product.is_variable_weight,
        "requires_age_check": product.requires_age_check,
    }


@dataclass(frozen=True, slots=True)
class Scalars:
    """the columns product_state denormalises out of a version's json, and the
    values event derivation compares. computed from json only, so a baseline
    version from yesterday and today's summary go through the same code."""

    name: str
    brand: str
    category_ids: list[str]
    unit_price: Decimal | None
    previous_price: Decimal | None
    bulk_price: Decimal | None
    reference_price: Decimal | None
    tracked_price: Decimal | None
    tracked_price_basis: str
    unit_size: Decimal | None
    size_format: str
    reference_format: str
    approximate_size: bool
    official_discount: bool
    published: bool | None


def tracked_price(price: JsonObject) -> tuple[Decimal | None, str]:
    # PRODUCT.md: variable-weight products are tracked by their reference price
    # per kilo or litre, because the basket price only reflects the cut. the
    # summary marks those with `approximate_size`.
    reference = _parse_decimal(price["reference"])
    if price["approximate_size"] and reference is not None:
        return reference, "reference"
    return _parse_decimal(price["unit"]), "unit"


def scalars(data: JsonObject) -> Scalars:
    price = data["price"]
    tracked, basis = tracked_price(price)
    return Scalars(
        name=data["name"],
        brand=data["brand"] or "",
        category_ids=[category["id"] for category in data["categories"]],
        unit_price=_parse_decimal(price["unit"]),
        previous_price=_parse_decimal(price["previous"]),
        bulk_price=_parse_decimal(price["bulk"]),
        reference_price=_parse_decimal(price["reference"]),
        tracked_price=tracked,
        tracked_price_basis=basis,
        unit_size=_parse_decimal(price["unit_size"]),
        size_format=price["size_format"] or "",
        reference_format=price["reference_format"] or "",
        approximate_size=price["approximate_size"],
        official_discount=price["is_discounted"],
        published=data["published"],
    )


DESCRIPTIVE_KEYS = (
    "name",
    "brand",
    "slug",
    "packaging",
    "main_feature",
    "thumbnail",
)


def descriptive_change(old: JsonObject, new: JsonObject) -> bool:
    """did anything change that would make the detail record worth refetching?
    price-only changes do not (COLLECTION.md)."""

    if any(old[key] != new[key] for key in DESCRIPTIVE_KEYS):
        return True
    old_ids = [category["id"] for category in old["categories"]]
    new_ids = [category["id"] for category in new["categories"]]
    return old_ids != new_ids
