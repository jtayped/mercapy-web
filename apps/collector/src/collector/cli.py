"""`collector` command line. every subcommand is idempotent and safe to
reschedule; the crontab runs them under supercronic."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from collector.config import Settings
from collector.db import Connection, connect, now_utc
from collector.details import enqueue_sample, process_detail_queue
from collector.discovery import (
    discover_batch,
    download_geonames,
    import_postal_codes,
    seed_historical_warehouses,
)
from collector.ingestion import collect_warehouse
from collector.migrations import apply_migrations
from collector.names import collect_spanish_names
from collector.store import mark_national_discontinuations
from collector.sweep import due_warehouses, fail_abandoned_runs

log = logging.getLogger("collector")


def _collect(conn: Connection, settings: Settings, args: argparse.Namespace) -> int:
    if args.warehouses:
        codes = [code.strip().lower() for code in args.warehouses]
    elif args.include_all:
        codes = [
            row["code"]
            for row in conn.execute(
                "select code from warehouse where active order by code"
            )
        ]
    else:
        codes = due_warehouses(conn, stale_hours=settings.stale_hours)
    if args.limit:
        codes = codes[: args.limit]
    failures = 0
    for code in codes:
        result = collect_warehouse(conn, settings, code)
        collected, reported = result.collected_count or 0, result.reported_count or 0
        print(f"{code}: {result.status} {collected}/{reported}")
        failures += result.status != "success"
    return 1 if failures and failures == len(codes) else 0


def _details(conn: Connection, settings: Settings, args: argparse.Namespace) -> int:
    stored, failed, dropped = process_detail_queue(conn, settings, limit=args.limit)
    print(f"details: {stored} stored, {failed} failed, {dropped} dropped")
    return 0


def _discover(conn: Connection, settings: Settings, args: argparse.Namespace) -> int:
    for row in discover_batch(
        conn, settings, limit=args.limit, max_age_days=args.max_age_days
    ):
        print(f"{row['postal_code']}: {row['warehouse_code'] or row['last_error']}")
    return 0


def _import_postcodes(
    conn: Connection, settings: Settings, args: argparse.Namespace
) -> int:
    if args.path is None:
        created = import_postal_codes(conn, download_geonames(settings))
    else:
        path: Path = args.path
        with path.open(encoding="utf-8") as source:
            created = import_postal_codes(conn, source)
    print(f"imported {created} postal code candidates")
    return 0


def _bootstrap(conn: Connection, settings: Settings, args: argparse.Namespace) -> int:
    """what a fresh deployment needs before the crontab takes over. every step
    is idempotent, so the compose `migrate` service runs it on each deploy."""

    _migrate(conn, settings, args)
    _seed(conn, settings, args)
    row = conn.execute(
        "select not exists(select 1 from postal_code) as empty"
    ).fetchone()
    if row and row["empty"]:
        args.path = None
        _import_postcodes(conn, settings, args)
    return 0


def _seed(conn: Connection, settings: Settings, args: argparse.Namespace) -> int:
    print(f"seeded {seed_historical_warehouses(conn)} inactive warehouses")
    return 0


def _names(conn: Connection, settings: Settings, args: argparse.Namespace) -> int:
    print(
        f"updated {collect_spanish_names(conn, settings, args.warehouse)} spanish names"
    )
    return 0


def _sweep(conn: Connection, settings: Settings, args: argparse.Namespace) -> int:
    abandoned = fail_abandoned_runs(conn)
    discontinued = mark_national_discontinuations(
        conn, settings, now=now_utc(), run_id=None
    )
    sampled = enqueue_sample(conn, limit=args.sample)
    print(
        f"sweep: {abandoned} abandoned runs, {discontinued} discontinued,"
        f" {sampled} sampled"
    )
    return 0


def _migrate(conn: Connection, settings: Settings, args: argparse.Namespace) -> int:
    applied = apply_migrations(conn, settings.migrations_dir)
    print(
        f"applied {len(applied)} migrations"
        + (": " + ", ".join(applied) if applied else "")
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="collector")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect", help="collect due warehouse catalogs")
    collect.add_argument("--warehouse", action="append", dest="warehouses")
    collect.add_argument("--all", action="store_true", dest="include_all")
    collect.add_argument("--limit", type=int)
    collect.set_defaults(run=_collect)

    details = commands.add_parser("details", help="work the detail queue")
    details.add_argument("--limit", type=int, default=125)
    details.set_defaults(run=_details)

    discover = commands.add_parser("discover", help="resolve stale postal codes")
    discover.add_argument("--limit", type=int, default=25)
    discover.add_argument("--max-age-days", type=int, default=30)
    discover.set_defaults(run=_discover)

    postcodes = commands.add_parser("import-postcodes", help="load geonames candidates")
    postcodes.add_argument(
        "path", type=Path, nargs="?", help="ES.txt; downloads it if omitted"
    )
    postcodes.set_defaults(run=_import_postcodes)

    commands.add_parser(
        "bootstrap", help="migrate, seed, import geonames once"
    ).set_defaults(run=_bootstrap)

    commands.add_parser(
        "seed-warehouses", help="insert the historical codes"
    ).set_defaults(run=_seed)

    names = commands.add_parser("names-es", help="collect spanish names once")
    names.add_argument("--warehouse", required=True)
    names.set_defaults(run=_names)

    sweep = commands.add_parser(
        "sweep", help="abandoned runs, discontinuations, sample"
    )
    sweep.add_argument("--sample", type=int, default=50)
    sweep.set_defaults(run=_sweep)

    commands.add_parser("migrate", help="apply packages/db/drizzle").set_defaults(
        run=_migrate
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = Settings.from_env()
    with connect(settings.database_url) as conn:
        result: int = args.run(conn, settings, args)
        return result


if __name__ == "__main__":
    raise SystemExit(main())
