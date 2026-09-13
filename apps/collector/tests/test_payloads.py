from __future__ import annotations

import json
from decimal import Decimal

from jsonschema import Draft202012Validator
from mercapy import Category, Price, Product, ProductDetails, ProductSummary

from collector.payloads import (
    comparable,
    descriptive_change,
    detail_data,
    fingerprint,
    scalars,
    summary_data,
    summary_fingerprint,
    tracked_price,
)

from .conftest import SCHEMA_DIR


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / f"{name}.json").read_text())
    return Draft202012Validator(schema)


def test_summary_data_matches_the_contract_schema() -> None:
    product = ProductSummary(
        id="1",
        name="Arròs",
        price=Price(unit=Decimal("1.20"), unit_size=Decimal("1"), size_format="kg"),
        categories=(
            Category(
                id="1",
                name="Arrossos",
                level=1,
                children=(Category(id="12", name="Arròs rodó", level=2),),
            ),
        ),
    )
    payload = summary_data(product)
    _validator("summary-data").validate(payload)
    assert payload["price"]["unit"] == "1.20"
    assert [category["id"] for category in payload["categories"]] == ["1", "12"]
    assert payload["categories"][1]["parent_id"] == "1"
    assert fingerprint(payload) == fingerprint(json.loads(json.dumps(payload)))


def test_detail_data_matches_the_contract_schema_and_drops_marketing_copy() -> None:
    product = Product(
        id="1",
        name="Arròs",
        ean="8410000000000",
        details=ProductDetails(origin="Espanya", description="El millor arròs"),
    )
    payload = detail_data(product)
    _validator("detail-data").validate(payload)
    assert "description" not in payload
    assert payload["origin"] == "Espanya"


def test_tracked_price_uses_reference_for_variable_weight() -> None:
    fixed = summary_data(
        ProductSummary(
            id="1", name="x", price=Price(unit=Decimal("2"), reference=Decimal("4"))
        )
    )
    variable = summary_data(
        ProductSummary(
            id="2",
            name="Lluç",
            price=Price(
                unit=Decimal("12.77"), reference=Decimal("11.50"), approximate_size=True
            ),
        )
    )
    assert tracked_price(fixed["price"]) == (Decimal("2"), "unit")
    assert tracked_price(variable["price"]) == (Decimal("11.50"), "reference")
    assert scalars(variable).tracked_price_basis == "reference"


def test_descriptive_change_ignores_price_only_changes() -> None:
    before = summary_data(
        ProductSummary(id="1", name="x", price=Price(unit=Decimal("1")))
    )
    after = summary_data(
        ProductSummary(id="1", name="x", price=Price(unit=Decimal("2")))
    )
    renamed = summary_data(
        ProductSummary(id="1", name="y", price=Price(unit=Decimal("2")))
    )
    assert not descriptive_change(before, after)
    assert descriptive_change(before, renamed)


def test_fingerprint_ignores_stored_but_uncompared_fields() -> None:
    def product(share_url: str, order: int) -> ProductSummary:
        return ProductSummary(
            id="1",
            name="Arròs",
            share_url=share_url,
            price=Price(unit=Decimal("1"), minimum_amount=Decimal(order)),
            categories=(Category(id="1", name="Arrossos", order=order),),
        )

    first = summary_data(product("https://a", 1))
    second = summary_data(product("https://b", 2))
    _validator("summary-data").validate(first)
    assert first != second
    assert summary_fingerprint(first) == summary_fingerprint(second)
    assert "share_url" not in comparable(first)
    assert "order" not in comparable(first)["categories"][0]
