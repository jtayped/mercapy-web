from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx
from mercapy import CatalogResult, Mercadona, Product

from collector.config import Settings

POSTAL_CODE_URL = "https://tienda.mercadona.es/api/postal-codes/actions/change-pc/"


class CatalogClient(Protocol):
    def __enter__(self) -> CatalogClient: ...
    def __exit__(self, *args: object) -> None: ...
    def get_indexed_catalog(self) -> CatalogResult: ...
    def get_product(self, product_id: str | int) -> Product: ...


ClientFactory = Callable[..., Any]


def open_client(
    settings: Settings, warehouse: str, *, language: str | None = None
) -> Mercadona:
    client = Mercadona(
        warehouse,
        language=language or settings.language,
        min_request_interval=settings.request_interval,
    )
    # POLICY.md wants an identifiable user agent with a contact address. the
    # library has no knob for it yet, so the header is set on its http client.
    # TODO(joel, 2026-10): add a `user_agent` argument to mercapy and drop this.
    client._client.headers["User-Agent"] = settings.user_agent
    return client


def resolve_warehouse(settings: Settings, postal_code: str) -> str:
    """resolve a postal code with the project's user agent."""

    response = httpx.put(
        POSTAL_CODE_URL,
        json={"new_postal_code": postal_code},
        headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
        timeout=10.0,
        follow_redirects=False,
    )
    response.raise_for_status()
    warehouse = str(response.headers.get("X-Customer-Wh", "")).strip().lower()
    if not warehouse:
        raise ValueError(f"postal code {postal_code} returned no warehouse header")
    return warehouse
