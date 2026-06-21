from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import fakeredis.aioredis
from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as srepo
from app.db.repositories import technical_snapshots as trepo
from app.db.seed import seed_stocks
from app.jobs.indicator_calculator import recompute_indicators
from app.providers.breaker import CircuitBreaker
from tests._fakes import FakeBarProvider

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
NOW = datetime(2026, 6, 12, 6, 0, tzinfo=timezone.utc)


def _frame(n=260):
    close = pd.Series([100.0 + 0.2 * i for i in range(n)])
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": close.values, "high": (close + 0.1).values,
                         "low": (close - 0.1).values, "close": close.values,
                         "volume": [100000.0 + i for i in range(n)]}, index=idx)


@pytest.mark.asyncio
async def test_recompute_indicators_covers_all_active_stocks(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG); seed_stocks(db, CSV)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    bars = FakeBarProvider(bars=_frame())
    async with connect(db) as con:
        n_active = len(await srepo.list_active_all(con))
    total = await recompute_indicators(db, r, cb, bars_provider=bars, now=NOW)
    assert total == n_active * 4    # every active stock x 4 intervals
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        snap = await trepo.get_latest_snapshot(con, ref.id, "1h")
    assert snap is not None and snap["rsi"] == 100.0
