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
from app.providers.breaker import CircuitBreaker
from app.providers.retry import ProviderError
from app.services import indicator_pipeline as pipe
from tests._fakes import FakeBarProvider

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
NOW = datetime(2026, 6, 12, 6, 0, tzinfo=timezone.utc)


def _daily_frame(n=260):
    close = pd.Series([100.0 + 0.2 * i for i in range(n)])
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": close.values, "high": (close + 0.1).values,
                         "low": (close - 0.1).values, "close": close.values,
                         "volume": [100000.0 + i for i in range(n)]}, index=idx)


async def _seed(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG); seed_stocks(db, CSV)
    return db


@pytest.mark.asyncio
async def test_recompute_for_stock_writes_all_intervals(tmp_path):
    db = await _seed(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    bars = FakeBarProvider(bars=_daily_frame())
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
    written = await pipe.recompute_for_stock(db, ref, bars, cb, now=NOW)
    assert written == 4   # 5m, 15m, 1h, 1d
    async with connect(db) as con:
        snap = await trepo.get_latest_snapshot(con, ref.id, "1d")
    assert snap["rsi"] == 100.0       # strictly rising frame -> RSI 100
    assert snap["indicators"]["ema_stack_bullish"] is True


@pytest.mark.asyncio
async def test_recompute_skips_empty_frames(tmp_path):
    db = await _seed(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    bars = FakeBarProvider(bars=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
    written = await pipe.recompute_for_stock(db, ref, bars, cb, now=NOW)
    assert written == 0


@pytest.mark.asyncio
async def test_recompute_records_breaker_failure(tmp_path):
    db = await _seed(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    dead = FakeBarProvider(error=ProviderError("down"))
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
    written = await pipe.recompute_for_stock(db, ref, dead, cb, now=NOW)
    assert written == 0
    assert int(await r.get("cb:yfinance_bars:fails")) >= 4   # 4 intervals each failed


def test_is_first_bar_of_session_detects_overnight_gap():
    # last two 5m bars span an overnight gap -> first bar of a new session.
    idx = pd.to_datetime(["2026-06-11 06:25", "2026-06-12 00:00"]).tz_localize("UTC")
    frame = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
    assert pipe._is_first_bar_of_session(frame, "5m") is True


def test_is_first_bar_of_session_false_for_daily():
    idx = pd.to_datetime(["2026-06-10", "2026-06-11"]).tz_localize("UTC")
    frame = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
    assert pipe._is_first_bar_of_session(frame, "1d") is False
