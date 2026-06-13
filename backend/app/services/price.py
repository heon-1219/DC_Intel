import json
from datetime import datetime, timezone

from app.providers.base import PriceQuote, StockRef

STALE_AFTER_S = 5 * 60


def _key(symbol: str, exchange: str) -> str:
    return f"px:quote:{symbol}:{exchange}"


def provider_chain(region: str, *, yfinance, finnhub, pykrx) -> list:
    """Region-aware order: KR -> yfinance, pykrx; US -> yfinance, finnhub; else yfinance."""
    if region == "KR":
        return [yfinance, pykrx]
    if region == "US":
        return [yfinance, finnhub]
    return [yfinance]


async def fetch_and_cache(ref: StockRef, providers: list, redis, breaker) -> PriceQuote | None:
    """Try each non-open provider in order; cache the first success. None if all fail."""
    for p in providers:
        if await breaker.is_open(p.name):
            continue
        try:
            q = await p.fetch_quote(ref)
        except Exception:  # noqa: BLE001 - providers normalize to ProviderError; treat as failure
            await breaker.record_failure(p.name)
            continue
        await breaker.record_success(p.name)
        await redis.set(_key(ref.symbol, ref.exchange), json.dumps({
            "price": q.price, "previous_close": q.previous_close, "volume": q.volume,
            "day_high": q.day_high, "day_low": q.day_low, "currency": ref.currency,
            "as_of": q.as_of.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": p.name,
        }))
        return q
    return None


async def read_cached(redis, symbol: str, exchange: str) -> dict | None:
    raw = await redis.get(_key(symbol, exchange))
    return json.loads(raw) if raw else None


def is_stale(as_of: datetime, market_state: str, now: datetime) -> bool:
    if market_state != "open":
        return False
    return (now - as_of).total_seconds() > STALE_AFTER_S
