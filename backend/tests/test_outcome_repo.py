"""M7a outcome-grading repo (win-loss §5.4): find_due + atomic record_outcome (one outcome per
prediction, marks checked in the same transaction)."""
import sqlite3
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import predictions as repo
from app.db.repositories import stocks as srepo
from app.db.repositories import users as urepo
from app.db.seed import seed_stocks

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


async def _pred(con, uid, sid, *, tf="5d", direction="up", window):
    return await repo.insert_prediction(
        con, user_id=uid, stock_id=sid, timeframe=tf, direction=direction, confidence=66,
        reasoning_json={"entry_price": 100.0, "neutral_band_pct": 0.5},
        model_version="5d-lr-20260620.1", window_closes_at=window)


async def _setup(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        u = await urepo.create_user(con, "a@x.com", "h", "en")
        s = await srepo.get_stock(con, "005930", "KRX")
    return db, u["id"], s.id


@pytest.mark.asyncio
async def test_find_due_returns_matured_ungraded_ordered(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    async with connect(db) as con:
        await _pred(con, uid, sid, window="2026-06-20T00:00:00Z")
        await _pred(con, uid, sid, window="2026-06-18T00:00:00Z")
        await _pred(con, uid, sid, window="2099-01-01T00:00:00Z")   # future -> not due
        due = await repo.find_due(con, "2026-06-21T00:00:00Z", limit=10)
    assert [d["window_closes_at"] for d in due] == ["2026-06-18T00:00:00Z", "2026-06-20T00:00:00Z"]
    assert "reasoning_json" in due[0] and due[0]["direction"] == "up"


@pytest.mark.asyncio
async def test_record_outcome_grades_and_drops_from_due(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    async with connect(db) as con:
        pid = await _pred(con, uid, sid, window="2026-06-20T00:00:00Z")
        await repo.record_outcome(con, prediction_id=pid, actual_direction="up",
                                  actual_price_change_percent=1.2, marked_correct=1,
                                  exit_price=101.2, high_impact_event_overlap=0,
                                  checked_at_iso="2026-06-21T00:01:00Z")
        due = await repo.find_due(con, "2026-06-21T00:00:00Z", limit=10)
        cur = await con.execute("SELECT marked_correct, exit_price FROM prediction_outcomes WHERE prediction_id=?", (pid,))
        row = await cur.fetchone()
    assert due == []                       # graded -> checked_at set -> no longer due
    assert row["marked_correct"] == 1 and row["exit_price"] == 101.2


@pytest.mark.asyncio
async def test_record_outcome_is_unique_per_prediction(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    async with connect(db) as con:
        pid = await _pred(con, uid, sid, window="2026-06-20T00:00:00Z")
        await repo.record_outcome(con, prediction_id=pid, actual_direction="up",
                                  actual_price_change_percent=1.0, marked_correct=1,
                                  exit_price=101.0, high_impact_event_overlap=0,
                                  checked_at_iso="2026-06-21T00:01:00Z")
        with pytest.raises(sqlite3.IntegrityError):     # one outcome per prediction
            await repo.record_outcome(con, prediction_id=pid, actual_direction="down",
                                      actual_price_change_percent=-1.0, marked_correct=0,
                                      exit_price=99.0, high_impact_event_overlap=0,
                                      checked_at_iso="2026-06-21T00:02:00Z")
