from datetime import datetime, timezone

from app.db.connection import connect
from app.db.repositories import stocks as repo
from app.services.indicator_pipeline import recompute_for_stock


async def recompute_indicators(db_path: str, redis, breaker, *, bars_provider,
                               now: datetime | None = None) -> int:
    """Recompute + persist indicator snapshots for every active stock across all
    intervals. Returns total snapshots written. v1 scope = full universe (the §10.2
    'active symbols' narrowing waits for M6's predictions table)."""
    now = now or datetime.now(timezone.utc)
    async with connect(db_path) as con:
        refs = await repo.list_active_all(con)
    total = 0
    for ref in refs:
        total += await recompute_for_stock(db_path, ref, bars_provider, breaker, now=now)
    return total


def _main() -> None:
    import asyncio
    import sys

    from app.cache import redis as cache_redis
    from app.config import get_settings
    from app.core.instrument import parse_instrument
    from app.db.repositories import technical_snapshots as trepo
    from app.providers.breaker import CircuitBreaker
    from app.providers.yfinance_bars import YFinanceBarProvider

    async def _run() -> None:
        s = get_settings()
        r = cache_redis.get_client()
        cb = CircuitBreaker(r)
        bars = YFinanceBarProvider()
        if len(sys.argv) > 1:                      # single-symbol smoke: SYMBOL:EXCHANGE
            sym, exch = parse_instrument(sys.argv[1])
            async with connect(s.sqlite_path) as con:
                ref = await repo.get_stock(con, sym, exch)
            n = await recompute_for_stock(s.sqlite_path, ref, bars, cb,
                                          now=datetime.now(timezone.utc))
            async with connect(s.sqlite_path) as con:
                snap = await trepo.get_latest_snapshot(con, ref.id, "1d")
            print(f"wrote {n} snapshots for {sys.argv[1]}; "
                  f"1d rsi={snap and snap['rsi']} ema_200={snap and snap['ema_200']}")
        else:
            total = await recompute_indicators(s.sqlite_path, r, cb, bars_provider=bars)
            print(f"recompute_indicators wrote {total} snapshots")
        await r.aclose()

    asyncio.run(_run())


if __name__ == "__main__":
    _main()
