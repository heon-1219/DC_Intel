import fakeredis.aioredis
import pytest

from app.providers.breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_opens_after_threshold_and_clears_on_success():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r, threshold=3, cooldown_s=60)
    assert await cb.is_open("yfinance") is False
    for _ in range(3):
        await cb.record_failure("yfinance")
    assert await cb.is_open("yfinance") is True
    await cb.record_success("yfinance")
    assert await cb.is_open("yfinance") is False


@pytest.mark.asyncio
async def test_below_threshold_stays_closed():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r, threshold=3)
    await cb.record_failure("pykrx")
    await cb.record_failure("pykrx")
    assert await cb.is_open("pykrx") is False
