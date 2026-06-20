from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import sentiment_logs as repo
from app.db.repositories import stocks as srepo
from app.db.seed import seed_stocks

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


@pytest.mark.asyncio
async def test_insert_and_get_latest(tmp_path):
    db = await _db(tmp_path)
    bd = {"schema_version": 1, "timeframe_scores": {"24h": {"score": 31.0}}}
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await repo.insert_log(con, ref.id, "2026-06-16T05:00:00Z", 31.0, bd)
        snap = await repo.get_latest(con, ref.id)
    assert snap["aggregate_sentiment_score"] == 31.0
    assert snap["source_breakdown"]["timeframe_scores"]["24h"]["score"] == 31.0


@pytest.mark.asyncio
async def test_get_latest_at_excludes_future(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        for ts, sc in [("2026-06-16T03:00:00Z", 10.0),
                       ("2026-06-16T05:00:00Z", 20.0),
                       ("2026-06-16T07:00:00Z", 30.0)]:
            await repo.insert_log(con, ref.id, ts, sc, {"timeframe_scores": {"24h": {"score": sc}}})
        snap = await repo.get_latest_at(con, ref.id, "2026-06-16T06:00:00Z")
    assert snap["timestamp"] == "2026-06-16T05:00:00Z"   # latest <= as_of, not the 07:00 future row
    assert snap["source_breakdown"]["timeframe_scores"]["24h"]["score"] == 20.0


@pytest.mark.asyncio
async def test_get_latest_at_none_before_any(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await repo.insert_log(con, ref.id, "2026-06-16T05:00:00Z", 20.0, {"v": 1})
        assert await repo.get_latest_at(con, ref.id, "2026-06-16T04:00:00Z") is None


@pytest.mark.asyncio
async def test_upsert_same_timestamp_and_null_score(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        await repo.insert_log(con, ref.id, "2026-06-16T05:00:00Z", 10.0, {"v": 1})
        await repo.insert_log(con, ref.id, "2026-06-16T05:00:00Z", None, {"v": 2})  # null score ok
        cur = await con.execute("SELECT COUNT(*) c FROM sentiment_logs WHERE stock_id=?", (ref.id,))
        count = (await cur.fetchone())["c"]
        snap = await repo.get_latest(con, ref.id)
    assert count == 1   # upsert on (stock_id, timestamp)
    assert snap["aggregate_sentiment_score"] is None
