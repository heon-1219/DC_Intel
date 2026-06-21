"""M7e outcome_checker job (win-loss §5.4): scan due -> resolve exit -> grade / defer / park ->
record outcome (atomic) -> clear retry -> invalidate accuracy cache."""
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo
from app.db.repositories import users as urepo
from app.db.repositories import technical_snapshots as trepo
from app.db.seed import seed_stocks
from app.jobs.outcome_checker import run_outcome_checker
from app.tracking import retry as rt

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
NOW = "2026-06-27T00:00:00Z"


async def _setup(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    async with connect(db) as con:
        u = await urepo.create_user(con, "a@x.com", "h", "en")
        s = await srepo.get_stock(con, "005930", "KRX")
    return db, u["id"], s.id


async def _pred(con, uid, sid, *, entry=100.0, band=0.5, direction="up",
                window="2026-06-26T00:00:00Z"):
    return await prepo.insert_prediction(
        con, user_id=uid, stock_id=sid, timeframe="5d", direction=direction, confidence=66,
        reasoning_json={"entry_price": entry, "neutral_band_pct": band},
        model_version="5d-lr-20260620.1", window_closes_at=window)


@pytest.mark.asyncio
async def test_grades_a_matured_prediction(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    async with connect(db) as con:
        pid = await _pred(con, uid, sid, entry=100.0, direction="up")
        await trepo.upsert_snapshot(con, sid, "1d", "2026-06-26T06:30:00Z", {"close": 103.0})  # +3% up
    graded = await run_outcome_checker(db, r, now=NOW)
    async with connect(db) as con:
        cur = await con.execute("SELECT actual_direction, marked_correct, checked_at FROM "
                                "prediction_outcomes o JOIN predictions p ON p.id=o.prediction_id "
                                "WHERE p.id=?", (pid,))
        row = await cur.fetchone()
    assert graded == 1
    assert row["actual_direction"] == "up" and row["marked_correct"] == 1


@pytest.mark.asyncio
async def test_defers_when_exit_price_pending(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    async with connect(db) as con:
        pid = await _pred(con, uid, sid)        # no snapshot at/after window -> pending
    graded = await run_outcome_checker(db, r, now=NOW)
    assert graded == 0
    assert await rt.attempts_for(r, pid) == 1   # a retry attempt was recorded


@pytest.mark.asyncio
async def test_split_suspect_is_parked(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    async with connect(db) as con:
        pid = await _pred(con, uid, sid, entry=100.0)
        await trepo.upsert_snapshot(con, sid, "1d", "2026-06-26T06:30:00Z", {"close": 250.0})  # +150%
    graded = await run_outcome_checker(db, r, now=NOW)
    assert graded == 0 and await rt.is_parked(r, pid) is True
    # parked -> skipped on the next run (still not graded)
    assert await run_outcome_checker(db, r, now=NOW) == 0


@pytest.mark.asyncio
async def test_grade_invalidates_accuracy_cache(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await r.set("acc:005930:KRX:all:all", "cached")
    async with connect(db) as con:
        await _pred(con, uid, sid, entry=100.0)
        await trepo.upsert_snapshot(con, sid, "1d", "2026-06-26T06:30:00Z", {"close": 103.0})
    await run_outcome_checker(db, r, now=NOW)
    assert await r.get("acc:005930:KRX:all:all") is None   # busted on grade
