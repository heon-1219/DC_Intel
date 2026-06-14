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


@pytest.mark.asyncio
async def test_list_active_all_includes_indexes(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        refs = await srepo.list_active_all(con)
    assert len(refs) == 12   # 7 common/ADR + 5 index pseudo-rows in the seed
