"""M5c history backfill (prediction-model.md §7.1). Computes one technical_snapshot per historical
bar (trailing-window compute_indicators, identical math + timestamp format to the live recompute job)
so the feature builder + dataset have dense as-of history. Machinery tested on a synthetic OHLCV
frame; the real run fetches live yfinance history."""
from pathlib import Path

import pandas as pd
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as srepo
from app.db.repositories import technical_snapshots as trepo
from app.db.seed import seed_stocks
from app.ml.backfill import backfill_bars

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


def _bars(n=60):
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    close = pd.Series([100.0 + i * 0.5 for i in range(n)])
    return pd.DataFrame({"open": close.values, "high": (close + 1).values,
                         "low": (close - 1).values, "close": close.values,
                         "volume": [1_000_000.0 + (i % 5) * 1000 for i in range(n)]}, index=idx)


@pytest.mark.asyncio
async def test_backfill_writes_one_snapshot_per_bar(tmp_path):
    db = await _db(tmp_path)
    bars = _bars(60)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        written = await backfill_bars(con, ref, "1d", bars, start_min=20)
        latest = await trepo.get_latest_snapshot(con, ref.id, "1d")
        recent = await trepo.get_recent_at(con, ref.id, "1d", "2026-12-31T00:00:00Z", limit=4)
    assert written == 40                                      # bars 20..59
    assert latest["indicators"]["close"] == pytest.approx(100.0 + 59 * 0.5)
    assert latest["indicators"]["rsi_14"] is not None         # enough trailing history
    # dense + consecutive, newest first (so dataset/builder can step t, t-1, t-3)
    ts = [r["timestamp"] for r in recent]
    assert ts == ["2026-03-01T00:00:00Z", "2026-02-28T00:00:00Z",   # 2026 is not a leap year
                  "2026-02-27T00:00:00Z", "2026-02-26T00:00:00Z"]


@pytest.mark.asyncio
async def test_backfill_timestamp_matches_live_format(tmp_path):
    # identical to indicator_pipeline._iso so backfilled + live snapshots interleave/ dedupe.
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await backfill_bars(con, ref, "1d", _bars(30), start_min=20)
        snap = await trepo.get_latest_at(con, ref.id, "1d", "2026-01-29T00:00:00Z")
    assert snap["timestamp"] == "2026-01-29T00:00:00Z"        # bar index 28 (2026-01-01 + 28d)


@pytest.mark.asyncio
async def test_distinct_references_resolved_from_seed(tmp_path):
    from app.db.repositories import stocks as srepo
    from app.ml.backfill import distinct_references
    db = await _db(tmp_path)
    async with connect(db) as con:
        refs = distinct_references(await srepo.list_active_all(con))
    # Samsung/Hynix/NVDA -> SOXX; AAPL -> ^N225; Hyundai/NAVER (empty) -> SPY; PKX -> 005490.KS
    assert set(refs) == {"SOXX", "^N225", "SPY", "005490.KS"}


@pytest.mark.asyncio
async def test_backfill_idempotent(tmp_path):
    db = await _db(tmp_path)
    bars = _bars(40)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await backfill_bars(con, ref, "1d", bars, start_min=20)
        await backfill_bars(con, ref, "1d", bars, start_min=20)   # re-run overwrites, no dupes
        cur = await con.execute(
            "SELECT COUNT(*) c FROM technical_snapshots WHERE stock_id=? AND bar_interval='1d'",
            (ref.id,))
        assert (await cur.fetchone())["c"] == 20
