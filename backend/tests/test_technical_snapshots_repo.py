from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as srepo
from app.db.repositories import technical_snapshots as trepo
from app.db.seed import seed_stocks

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


def _payload():
    return {
        "rsi_14": 73.4, "rsi_state": "overbought",
        "ema_5": 12.51, "ema_20": 11.98, "ema_50": 11.4, "ema_200": 10.85,
        "macd_line": 1.4, "macd_signal": 1.16, "macd_histogram": 0.24,
        "bb_middle": 50.0, "bb_upper": 52.4, "bb_lower": 47.6,
        "bb_percent_b": 1.04, "bb_bandwidth": 0.096, "bb_state": "breakout_up",
        "vol_z20": 1.9, "vol_state": "elevated", "flags": [],
    }


async def _seed_db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


@pytest.mark.asyncio
async def test_upsert_then_get_latest_roundtrips(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-12T06:30:00Z", _payload())
        snap = await trepo.get_latest_snapshot(con, ref.id, "1d")
    assert snap["rsi"] == 73.4            # scalar column mapped from rsi_14
    assert snap["macd"] == 1.4            # scalar column mapped from macd_line
    assert snap["bollinger_upper"] == 52.4
    assert snap["timestamp"] == "2026-06-12T06:30:00Z"
    assert snap["indicators"]["rsi_state"] == "overbought"   # parsed indicators_json


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_same_key(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-12T06:30:00Z", _payload())
        p2 = _payload(); p2["rsi_14"] = 50.0; p2["rsi_state"] = "neutral"
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-12T06:30:00Z", p2)
        cur = await con.execute(
            "SELECT COUNT(*) AS c FROM technical_snapshots WHERE stock_id=? AND bar_interval='1d'",
            (ref.id,))
        count = (await cur.fetchone())["c"]
        snap = await trepo.get_latest_snapshot(con, ref.id, "1d")
    assert count == 1            # same (stock, interval, timestamp) -> one row
    assert snap["rsi"] == 50.0   # overwritten


@pytest.mark.asyncio
async def test_get_latest_returns_none_when_empty(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        assert await trepo.get_latest_snapshot(con, ref.id, "5m") is None


async def _seed_series(con, ref):
    """Three daily snapshots on consecutive days, ascending rsi, for as-of tests."""
    for ts, rsi in [("2026-06-10T06:30:00Z", 40.0),
                    ("2026-06-11T06:30:00Z", 50.0),
                    ("2026-06-12T06:30:00Z", 60.0)]:
        p = _payload(); p["rsi_14"] = rsi
        await trepo.upsert_snapshot(con, ref.id, "1d", ts, p)


@pytest.mark.asyncio
async def test_get_latest_at_excludes_future(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await _seed_series(con, ref)
        snap = await trepo.get_latest_at(con, ref.id, "1d", "2026-06-11T12:00:00Z")
    assert snap["timestamp"] == "2026-06-11T06:30:00Z"   # latest <= as_of, NOT the 06-12 future bar
    assert snap["rsi"] == 50.0


@pytest.mark.asyncio
async def test_get_latest_at_inclusive_of_exact_as_of(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await _seed_series(con, ref)
        snap = await trepo.get_latest_at(con, ref.id, "1d", "2026-06-11T06:30:00Z")
    assert snap["timestamp"] == "2026-06-11T06:30:00Z"   # <= is inclusive


@pytest.mark.asyncio
async def test_get_latest_at_none_when_all_future(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await _seed_series(con, ref)
        assert await trepo.get_latest_at(con, ref.id, "1d", "2026-06-09T00:00:00Z") is None


@pytest.mark.asyncio
async def test_get_recent_at_returns_n_newest_first(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await _seed_series(con, ref)
        rows = await trepo.get_recent_at(con, ref.id, "1d", "2026-06-12T23:00:00Z", limit=2)
    assert [r["timestamp"] for r in rows] == ["2026-06-12T06:30:00Z", "2026-06-11T06:30:00Z"]
    assert rows[0]["indicators"]["rsi_14"] == 60.0   # parsed payload, newest first


@pytest.mark.asyncio
async def test_get_recent_at_bounded_by_as_of(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await _seed_series(con, ref)
        rows = await trepo.get_recent_at(con, ref.id, "1d", "2026-06-11T12:00:00Z", limit=10)
    assert [r["timestamp"] for r in rows] == ["2026-06-11T06:30:00Z", "2026-06-10T06:30:00Z"]


@pytest.mark.asyncio
async def test_list_active_all_includes_indexes(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        refs = await srepo.list_active_all(con)
    syms = {r.symbol for r in refs}
    # list_active_all INCLUDES the index pseudo-rows (the indicator job's scope).
    assert {"KOSPI", "NASDAQ_COMPOSITE", "SP500", "NIKKEI225", "DAX"} <= syms
    assert "005930" in syms and len(refs) >= 50
