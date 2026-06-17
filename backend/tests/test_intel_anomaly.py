"""Offline tests for the social-anomaly scan (market-intel-pipeline.md §9).

Deterministic: temp migrated+seeded SQLite + fakeredis + injected bar providers. No network,
no torch/transformers. A local MappedBarProvider returns a frame per ticker so trigger counts
are exact (the shared-frame FakeBarProvider would fire on every active name at once)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis.aioredis
import pandas as pd
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.seed import seed_stocks
from app.intel.anomaly import pct_change_over_window, scan_anomalies
from app.intel.config import INTEL_ANOMALY_WINDOW_MIN

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
NOW = datetime(2026, 6, 16, 14, 30, tzinfo=timezone.utc)


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


def _frame(closes, *, end=NOW, step_min=5):
    """A 5m bar frame: UTC DatetimeIndex ending at `end`, ascending, with a 'close' column."""
    n = len(closes)
    idx = pd.DatetimeIndex(
        [end - timedelta(minutes=step_min * (n - 1 - i)) for i in range(n)], tz="UTC")
    return pd.DataFrame({"close": closes}, index=idx)


def _flat_frame(price=100.0, n=13):
    return _frame([price] * n)


def _jump_frame(start=100.0, end_price=103.5, n=13):
    """13 5m bars ending at NOW. The 30-min-back anchor (index -7) sits in the flat `start`
    region; the step to `end_price` lands after it, so the change over INTEL_ANOMALY_WINDOW_MIN
    is (end_price-start)/start*100 (default ~+3.5%)."""
    # indices 0..6 = start (index 6 is the now-30min anchor), indices 7..12 = end_price.
    return _frame([start] * 7 + [end_price] * (n - 7))


class MappedBarProvider:
    """fetch_bars(ref, interval) -> the frame mapped for ref.symbol, else a default flat frame."""

    name = "yfinance_bars"

    def __init__(self, by_symbol: dict, default=None):
        self._by_symbol = by_symbol
        self._default = default if default is not None else _flat_frame()
        self.calls = 0

    async def fetch_bars(self, ref, interval):
        self.calls += 1
        return self._by_symbol.get(ref.symbol, self._default)


async def _insert_event(db, *, country: str, impact: str, event_time: datetime):
    """Direct INSERT of a minimal economic_events row (avoids the registry/canonicalize deps)."""
    async with connect(db) as con:
        await con.execute(
            "INSERT INTO economic_events "
            "(event_name, event_time, impact_level, provider, event_type, country, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'scheduled')",
            ("FOMC Rate Decision",
             event_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
             impact, "test", "us_fomc", country))
        await con.commit()


# --- (4) pure math -----------------------------------------------------------------------

def test_pct_change_over_window_math():
    # 13 bars at 5m: now-anchor = last (110), then-anchor = bar at/<= now-30min (6 bars back).
    frame = _frame([100, 100, 100, 100, 100, 100, 100, 102, 104, 106, 108, 110, 110])
    # now-30min lands on index -7 (value 100); p_now = 110 -> +10%.
    change = pct_change_over_window(frame, 30, NOW)
    assert change == pytest.approx(10.0)

    # window longer than available history -> None (no then-anchor)
    assert pct_change_over_window(_frame([100, 101]), 30, NOW) is None
    # empty / missing column -> None
    assert pct_change_over_window(pd.DataFrame({"close": []}), 30, NOW) is None


# --- (1) trigger: >=3% jump, no high-impact event ----------------------------------------

@pytest.mark.asyncio
async def test_jump_with_no_event_triggers(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    bars = MappedBarProvider({"AAPL": _jump_frame()})  # everyone else flat

    n = await scan_anomalies(db, r, bars, now=NOW)
    assert n == 1
    assert bars.calls >= 1

    keys = [k async for k in r.scan_iter(match="intel:anomaly:AAPL:NASDAQ:*")]
    assert len(keys) == 1
    import json
    payload = json.loads(await r.get(keys[0]))
    assert payload["direction"] == "up"
    assert payload["change_pct"] >= 3.0
    assert payload["window_minutes"] == INTEL_ANOMALY_WINDOW_MIN
    assert payload["stock"] == {"symbol": "AAPL", "exchange": "NASDAQ"}


# --- (2) suppressed: same jump but a high-impact US event within ±60min -------------------

@pytest.mark.asyncio
async def test_jump_suppressed_by_high_impact_event(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    bars = MappedBarProvider({"AAPL": _jump_frame()})
    await _insert_event(db, country="US", impact="high", event_time=NOW + timedelta(minutes=20))

    n = await scan_anomalies(db, r, bars, now=NOW)
    assert n == 0
    keys = [k async for k in r.scan_iter(match="intel:anomaly:*")]
    assert keys == []


# --- (3) no trigger: tiny move below threshold -------------------------------------------

@pytest.mark.asyncio
async def test_tiny_move_does_not_trigger(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    bars = MappedBarProvider({"AAPL": _jump_frame(start=100.0, end_price=101.0)})  # +1%

    n = await scan_anomalies(db, r, bars, now=NOW)
    assert n == 0
    keys = [k async for k in r.scan_iter(match="intel:anomaly:*")]
    assert keys == []
