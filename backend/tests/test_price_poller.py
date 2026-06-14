from datetime import datetime, timezone
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.migrate import migrate
from app.db.seed import seed_stocks
from app.jobs.price_poller import poll_indexes, poll_region
from app.providers.base import PriceQuote
from app.providers.breaker import CircuitBreaker
from app.services import price as svc
from tests._fakes import FakeProvider

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
Q = PriceQuote(100.0, 99.0, 10, 101.0, 98.0, datetime(2026, 6, 12, 5, 30, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_poll_region_caches_each_kr_stock(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    fake = FakeProvider("yfinance", quote=Q)
    n = await poll_region(db, "KR", r, cb, yfinance=fake, finnhub=fake, pykrx=fake)
    assert n == 4  # 4 KR common stocks in the seed (index pseudo-rows excluded)
    assert (await svc.read_cached(r, "005930", "KRX"))["price"] == 100.0


@pytest.mark.asyncio
async def test_poll_region_counts_only_successes(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    from app.providers.retry import ProviderError
    dead = FakeProvider("yfinance", error=ProviderError("down"))
    n = await poll_region(db, "KR", r, cb, yfinance=dead, finnhub=dead, pykrx=dead)
    assert n == 0  # every provider fails -> nothing cached


@pytest.mark.asyncio
async def test_poll_indexes_caches_index_rows(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    fake = FakeProvider("yfinance", quote=Q)
    n = await poll_indexes(db, r, cb, yfinance=fake, finnhub=fake, pykrx=fake)
    assert n == 5  # KOSPI, NASDAQ_COMPOSITE, SP500, NIKKEI225, DAX
    assert (await svc.read_cached(r, "KOSPI", "INDEX"))["price"] == 100.0
