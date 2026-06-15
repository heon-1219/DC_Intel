"""Actual-value backfill (economic-calendar.md §11.3). Re-fetches the recent past window
from the providers and fills actual_vs_forecast for high/medium events whose number has since
published, flipping status to 'released'. The one-off T+5/+15/+45 date jobs are a latency
refinement on top of this correctness backfill (deferred)."""
from datetime import datetime, timedelta, timezone

from app.calendar.canonicalize import canonicalize
from app.calendar.merge import dedup
from app.calendar.registry import load_mega_caps, load_registry, load_sectors
from app.db.connection import connect
from app.db.repositories import economic_events as repo


def _has_actual(canon) -> bool:
    avf = canon.actual_vs_forecast
    return bool(avf and avf.get("metrics") and avf["metrics"][0].get("actual") is not None)


async def backfill_actuals(db_path: str, redis, breaker, *, providers, registry_path: str,
                           sectors_path: str, now: datetime | None = None,
                           lookback_days: int = 3) -> int:
    """Returns the number of events whose actual was filled."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)
    registry = load_registry(registry_path)
    sectors = load_sectors(sectors_path)
    mega = load_mega_caps(registry_path)

    raws = []
    for p in providers:
        try:
            raws.extend(await p.fetch_scheduled(start, now))
        except Exception:  # noqa: BLE001
            await breaker.record_failure(p.name)
            continue
        await breaker.record_success(p.name)

    canon = dedup([canonicalize(r, registry, sectors, mega) for r in raws])
    by_key = {(c.event_type, c.event_time[:10]): c for c in canon if _has_actual(c)}

    updated = 0
    now_iso = now.isoformat().replace("+00:00", "Z")
    async with connect(db_path) as con:
        for row in await repo.list_pending_actuals(con, now_iso):
            match = by_key.get((row["event_type"], row["event_time"][:10]))
            if match:
                await repo.set_actual(con, row["id"], match.actual_vs_forecast)
                updated += 1
    return updated
