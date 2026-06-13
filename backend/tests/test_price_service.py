from datetime import datetime, timedelta, timezone

import fakeredis.aioredis
import pytest

from app.providers.base import PriceQuote, StockRef
from app.providers.breaker import CircuitBreaker
from app.providers.retry import ProviderError
from app.services import price as svc
from tests._fakes import FakeProvider

REF = StockRef(1, "005930", "KRX", "KR", "KRW", "005930.KS", None)
Q = PriceQuote(84300.0, 83600.0, 11250300, 84600.0, 83400.0,
               datetime(2026, 6, 12, 5, 30, tzinfo=timezone.utc))


def test_provider_chain_by_region():
    assert svc.provider_chain("KR", yfinance="yf", finnhub="fh", pykrx="pk") == ["yf", "pk"]
    assert svc.provider_chain("US", yfinance="yf", finnhub="fh", pykrx="pk") == ["yf", "fh"]
    assert svc.provider_chain("JP", yfinance="yf", finnhub="fh", pykrx="pk") == ["yf"]


@pytest.mark.asyncio
async def test_fetch_and_cache_falls_through_chain_and_writes():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    p1 = FakeProvider("yfinance", error=ProviderError("down"))
    p2 = FakeProvider("pykrx", quote=Q)
    out = await svc.fetch_and_cache(REF, [p1, p2], r, cb)
    assert out is not None and out.price == 84300.0
    cached = await svc.read_cached(r, "005930", "KRX")
    assert cached["price"] == 84300.0 and cached["source"] == "pykrx"
    assert cached["currency"] == "KRW" and cached["as_of"].endswith("Z")


@pytest.mark.asyncio
async def test_open_breaker_skips_provider():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r, threshold=1)
    await cb.record_failure("yfinance")  # opens (threshold=1)
    p1 = FakeProvider("yfinance", quote=Q)
    p2 = FakeProvider("pykrx", quote=Q)
    await svc.fetch_and_cache(REF, [p1, p2], r, cb)
    assert p1.calls == 0 and p2.calls == 1  # yfinance skipped (open), pykrx used


@pytest.mark.asyncio
async def test_fetch_and_cache_returns_none_when_all_fail():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    p1 = FakeProvider("yfinance", error=ProviderError("down"))
    p2 = FakeProvider("pykrx", error=ProviderError("down"))
    assert await svc.fetch_and_cache(REF, [p1, p2], r, cb) is None
    assert await svc.read_cached(r, "005930", "KRX") is None


def test_is_stale_rules():
    now = datetime(2026, 6, 12, 5, 40, tzinfo=timezone.utc)
    fresh = now - timedelta(minutes=3)
    old = now - timedelta(minutes=10)
    assert svc.is_stale(old, "open", now) is True
    assert svc.is_stale(fresh, "open", now) is False
    assert svc.is_stale(old, "closed", now) is False  # never stale when closed
