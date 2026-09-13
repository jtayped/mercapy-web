"""housekeeping that no single collection owns."""

from __future__ import annotations

from collector.db import Connection


def fail_abandoned_runs(conn: Connection, *, max_hours: int = 6) -> int:
    """a run still `running` hours later belongs to a process that died. mark
    it so the health page and the due-warehouse selection see it."""

    result = conn.execute(
        """
        update crawl_run set status = 'failed', finished_at = now(),
            error = 'abandoned: the collector process did not finish this run'
        where status = 'running' and started_at < now() - make_interval(hours => %s)
        """,
        (max_hours,),
    )
    return result.rowcount


def due_warehouses(conn: Connection, *, stale_hours: int) -> list[str]:
    """active warehouses without a complete collection today, oldest first.
    one collection per warehouse per day is the target (COLLECTION.md)."""

    rows = conn.execute(
        """
        select code from warehouse
        where active
          and (last_observed_on is null
               or last_observed_on < (now() at time zone 'Europe/Madrid')::date)
          and (last_success_at is null
               or last_success_at <= now() - make_interval(hours => %s))
          and not exists (
            select 1 from crawl_run
            where crawl_run.warehouse_code = warehouse.code and status = 'running'
          )
        order by last_success_at nulls first, code
        """,
        (stale_hours // 3,),
    ).fetchall()
    return [row["code"] for row in rows]
