"""sync_calendar job (economic-calendar.md §11.1). Fetches the next `horizon_days` from all
providers, canonicalizes + dedups, and upserts into economic_events. The official-free
composite (seed + FRED + Finnhub) ALWAYS merges, so the calendar never depends solely on the
Investing.com scrape — that is the spec's circuit-breaker 'promotion' satisfied by design; the
breaker here records per-provider failures for ops alerting (§11.5)."""
from datetime import datetime, timedelta, timezone

from app.calendar.canonicalize import canonicalize
from app.calendar.merge import dedup
from app.calendar.registry import load_mega_caps, load_registry, load_sectors
from app.db.connection import connect
from app.db.repositories import economic_events as repo


async def sync_calendar(db_path: str, redis, breaker, *, providers, registry_path: str,
                        sectors_path: str, now: datetime | None = None,
                        horizon_days: int = 14) -> int:
    """Returns the number of events upserted."""
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(days=horizon_days)
    registry = load_registry(registry_path)
    sectors = load_sectors(sectors_path)
    mega = load_mega_caps(registry_path)

    raws = []
    for p in providers:
        try:
            raws.extend(await p.fetch_scheduled(now, end))
        except Exception:  # noqa: BLE001 - providers normalize to ProviderError
            await breaker.record_failure(p.name)
            continue
        await breaker.record_success(p.name)

    deduped = dedup([canonicalize(r, registry, sectors, mega) for r in raws])

    n = 0
    async with connect(db_path) as con:
        for ce in deduped:
            await repo.upsert_event(con, ce)
            n += 1

    await redis.set("cal:last_synced_at", now.isoformat().replace("+00:00", "Z"))
    try:  # best-effort invalidation of the M3b list cache
        stale = [k async for k in redis.scan_iter("cal:list:*")]
        if stale:
            await redis.delete(*stale)
    except Exception:  # noqa: BLE001 - scan_iter unsupported / no keys
        pass
    return n
