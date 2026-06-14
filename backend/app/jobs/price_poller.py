from app.db.connection import connect
from app.db.repositories import stocks as repo
from app.services import price as svc


async def poll_region(db_path: str, region: str, redis, breaker, *, yfinance, finnhub, pykrx) -> int:
    """Fetch + cache every active (non-index) stock in `region`. Returns count cached.

    The DB connection is held only to read the ref list, not during the (slow) fetches.
    v1 fetches per-stock; the batched-per-exchange optimization is a documented later refinement.
    """
    async with connect(db_path) as con:
        refs = await repo.list_active_by_region(con, region)
    return await _fetch_all(refs, redis, breaker, yfinance=yfinance, finnhub=finnhub, pykrx=pykrx)


async def poll_indexes(db_path: str, redis, breaker, *, yfinance, finnhub, pykrx) -> int:
    """Fetch + cache the index pseudo-rows (^KS11, ^IXIC, ...). yfinance handles index
    tickers; the fallbacks are never reached because yfinance is first in every chain."""
    async with connect(db_path) as con:
        refs = await repo.list_active_indexes(con)
    return await _fetch_all(refs, redis, breaker, yfinance=yfinance, finnhub=finnhub, pykrx=pykrx)


async def _fetch_all(refs, redis, breaker, *, yfinance, finnhub, pykrx) -> int:
    cached = 0
    for ref in refs:
        chain = svc.provider_chain(ref.region, yfinance=yfinance, finnhub=finnhub, pykrx=pykrx)
        if await svc.fetch_and_cache(ref, chain, redis, breaker) is not None:
            cached += 1
    return cached
