"""M7j operator backfill (win-loss §5.6): grade a parked prediction at a manual price, bypass split."""
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo
from app.db.repositories import users as urepo
from app.db.seed import seed_stocks
from app.tracking import retry as rt
from app.tracking.backfill import backfill_one

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
        pid = await prepo.insert_prediction(
            con, user_id=u["id"], stock_id=s.id, timeframe="5d", direction="up", confidence=66,
            reasoning_json={"entry_price": 100.0, "neutral_band_pct": 0.5},
            model_version="v", window_closes_at="2026-06-26T00:00:00Z")
    return db, pid


@pytest.mark.asyncio
async def test_backfill_grades_parked_bypassing_split(tmp_path):
    db, pid = await _setup(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await rt.park(r, pid, "split_suspect")
    ok = await backfill_one(db, r, pid, 250.0, now_iso=NOW)      # +150% would normally park
    assert ok is True
    async with connect(db) as con:
        cur = await con.execute("SELECT actual_direction, checked_at FROM prediction_outcomes o "
                                "JOIN predictions p ON p.id=o.prediction_id WHERE p.id=?", (pid,))
        row = await cur.fetchone()
    assert row["actual_direction"] == "up"                        # graded despite >35% move
    assert await rt.is_parked(r, pid) is False                    # unparked


@pytest.mark.asyncio
async def test_backfill_refuses_already_graded(tmp_path):
    db, pid = await _setup(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await backfill_one(db, r, pid, 101.0, now_iso=NOW)
    assert await backfill_one(db, r, pid, 105.0, now_iso=NOW) is False   # already graded


@pytest.mark.asyncio
async def test_backfill_unknown_prediction(tmp_path):
    db, _ = await _setup(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    assert await backfill_one(db, r, 999999, 100.0, now_iso=NOW) is False
