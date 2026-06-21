"""M7g accuracy_stats (win-loss §6): de-dup, directional win rate, neutral-as-loss, window filter."""
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import accuracy as acc
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo
from app.db.repositories import users as urepo
from app.db.seed import seed_stocks

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


async def _graded(con, uid, sid, *, tf="5d", direction="up", window, correct,
                  created="2026-06-20T00:00:00Z"):
    pid = await prepo.insert_prediction(
        con, user_id=uid, stock_id=sid, timeframe=tf, direction=direction, confidence=66,
        reasoning_json={"entry_price": 100.0, "neutral_band_pct": 0.5},
        model_version="5d-lr-20260620.1", window_closes_at=window)
    await con.execute("UPDATE predictions SET created_at=? WHERE id=?", (created, pid))
    await prepo.record_outcome(con, prediction_id=pid, actual_direction="up" if correct else "down",
                               actual_price_change_percent=1.0 if correct else -1.0,
                               marked_correct=correct, exit_price=101.0,
                               high_impact_event_overlap=0, checked_at_iso=NOW)
    return pid


@pytest.mark.asyncio
async def test_dedup_same_window_counts_once(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    async with connect(db) as con:
        b = await urepo.create_user(con, "b@x.com", "h", "en")
        # two users, SAME (tf, direction, window): one correct, one not -> MAX -> one correct row
        await _graded(con, uid, sid, direction="up", window="2026-06-26T00:00:00Z", correct=1)
        await _graded(con, b["id"], sid, direction="up", window="2026-06-26T00:00:00Z", correct=0)
        stats = await acc.accuracy_stats(con, sid, now_iso=NOW)
    assert stats["graded_total"] == 1 and stats["exact_accuracy_pct"] == 100.0


@pytest.mark.asyncio
async def test_directional_neutral_realized_is_loss(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    async with connect(db) as con:
        # an 'up' call that realized neutral (marked_correct=0) -> directional prediction, not a win
        pid = await prepo.insert_prediction(
            con, user_id=uid, stock_id=sid, timeframe="5d", direction="up", confidence=66,
            reasoning_json={"entry_price": 100.0, "neutral_band_pct": 0.5},
            model_version="v", window_closes_at="2026-06-26T00:00:00Z")
        await prepo.record_outcome(con, prediction_id=pid, actual_direction="neutral",
                                   actual_price_change_percent=0.2, marked_correct=0,
                                   exit_price=100.2, high_impact_event_overlap=0, checked_at_iso=NOW)
        stats = await acc.accuracy_stats(con, sid, now_iso=NOW)
    d = stats["directional"]
    assert d["predictions"] == 1 and d["wins"] == 0 and d["losses"] == 1 and d["win_rate_pct"] == 0.0


@pytest.mark.asyncio
async def test_window_filter_by_created_at(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    async with connect(db) as con:
        await _graded(con, uid, sid, window="2026-06-26T00:00:00Z", correct=1,
                      created="2026-06-20T00:00:00Z")          # recent
        await _graded(con, uid, sid, window="2026-02-10T00:00:00Z", correct=0,
                      created="2026-02-01T00:00:00Z")          # >30d before NOW
        all_stats = await acc.accuracy_stats(con, sid, window="all", now_iso=NOW)
        m30 = await acc.accuracy_stats(con, sid, window="30d", now_iso=NOW)
    assert all_stats["graded_total"] == 2 and m30["graded_total"] == 1


@pytest.mark.asyncio
async def test_low_sample_and_pending(tmp_path):
    db, uid, sid = await _setup(tmp_path)
    async with connect(db) as con:
        await _graded(con, uid, sid, window="2026-06-26T00:00:00Z", correct=1)
        # an ungraded (pending) prediction
        await prepo.insert_prediction(
            con, user_id=uid, stock_id=sid, timeframe="5d", direction="up", confidence=66,
            reasoning_json={"entry_price": 100.0, "neutral_band_pct": 0.5},
            model_version="v", window_closes_at="2099-01-01T00:00:00Z")
        stats = await acc.accuracy_stats(con, sid, now_iso=NOW)
    assert stats["low_sample"] is True and stats["pending"] == 1     # graded_total 1 < 20
    assert stats["by_timeframe"][0]["directional"]["win_rate_pct"] is None   # <20 -> null
