"""spanish names, collected once from a single warehouse because the name is
global (PRODUCT.md, search). cheap: one indexed catalog, about thirty requests."""

from __future__ import annotations

from collector.client import ClientFactory, open_client
from collector.config import Settings
from collector.db import Connection


def collect_spanish_names(
    conn: Connection,
    settings: Settings,
    warehouse_code: str,
    *,
    client_factory: ClientFactory | None = None,
) -> int:
    if client_factory is None:
        with open_client(settings, warehouse_code, language="es") as client:
            catalog = client.get_indexed_catalog()
    else:
        with client_factory(warehouse_code, language="es") as client:
            catalog = client.get_indexed_catalog()
    updated = 0
    with conn.transaction():
        for summary in catalog.products:
            result = conn.execute(
                "update product set name_es = %s where id = %s"
                " and name_es is distinct from %s",
                (summary.name, summary.id, summary.name),
            )
            updated += result.rowcount
    return updated
