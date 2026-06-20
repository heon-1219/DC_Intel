"""M6g predictions repository (SERVING §9, win-loss §3.1). Insert (synchronous audit), per-user
history with the prediction_outcomes LEFT JOIN, audit-duplicate lookup, recent-holdings."""
import json
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


async def _ins(con, *, user_id, stock_id, tf="5d", direction="up", window="2026-06-26T00:00:00Z"):
    return await repo.insert_prediction(
        con, user_id=user_id, stock_id=stock_id, timeframe=tf, direction=direction,
        confidence=66, reasoning_json={"schema_version": 1, "direction": direction},
        model_version="5d-lr-20260620.1", window_closes_at=window)


@pytest.mark.asyncio
async def test_insert_and_audit_lookup(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        u = await urepo.create_user(con, "a@x.com", "h", "en")
        s = await srepo.get_stock(con, "005930", "KRX")
        pid = await _ins(con, user_id=u["id"], stock_id=s.id)
        found = await repo.find_audit_row(con, u["id"], s.id, "5d", "2026-06-26T00:00:00Z")
        miss = await repo.find_audit_row(con, u["id"], s.id, "5d", "2099-01-01T00:00:00Z")
        cur = await con.execute("SELECT reasoning_json FROM predictions WHERE id=?", (pid,))
        rj = json.loads((await cur.fetchone())["reasoning_json"])
    assert pid and found["id"] == pid and miss is None
    assert rj["schema_version"] == 1                # reasoning_json round-trips (json_valid CHECK ok)


@pytest.mark.asyncio
async def test_history_user_isolation_and_total(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        a = await urepo.create_user(con, "a@x.com", "h", "en")
        b = await urepo.create_user(con, "b@x.com", "h", "en")
        s = await srepo.get_stock(con, "005930", "KRX")
        await _ins(con, user_id=a["id"], stock_id=s.id, window="2026-06-26T00:00:00Z")
        await _ins(con, user_id=a["id"], stock_id=s.id, window="2026-06-27T00:00:00Z")
        await _ins(con, user_id=b["id"], stock_id=s.id, window="2026-06-26T00:00:00Z")
        total, rows = await repo.list_user_history(con, user_id=a["id"], stock_id=s.id, limit=20, offset=0)
    assert total == 2 and len(rows) == 2            # only A's rows


@pytest.mark.asyncio
async def test_history_status_filter_and_outcome_mapping(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        u = await urepo.create_user(con, "a@x.com", "h", "en")
        s = await srepo.get_stock(con, "005930", "KRX")
        pending = await _ins(con, user_id=u["id"], stock_id=s.id, window="2026-06-26T00:00:00Z")
        graded = await _ins(con, user_id=u["id"], stock_id=s.id, window="2026-06-27T00:00:00Z")
        await con.execute(
            "INSERT INTO prediction_outcomes (prediction_id, actual_direction, "
            "actual_price_change_percent, marked_correct, exit_price) VALUES (?,?,?,?,?)",
            (graded, "up", 1.2, 1, 85000.0))
        await con.commit()
        tot_p, _ = await repo.list_user_history(con, user_id=u["id"], stock_id=s.id,
                                                status="pending", limit=20, offset=0)
        tot_c, rows_c = await repo.list_user_history(con, user_id=u["id"], stock_id=s.id,
                                                     status="correct", limit=20, offset=0)
    assert tot_p == 1                               # only the ungraded one
    assert tot_c == 1 and rows_c[0]["po_dir"] == "up" and rows_c[0]["po_correct"] == 1


@pytest.mark.asyncio
async def test_distinct_recent_stock_ids_cutoff(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        u = await urepo.create_user(con, "a@x.com", "h", "en")
        s = await srepo.get_stock(con, "005930", "KRX")
        pid = await _ins(con, user_id=u["id"], stock_id=s.id)
        # force an old created_at (older than the cutoff)
        await con.execute("UPDATE predictions SET created_at='2026-01-01T00:00:00Z' WHERE id=?", (pid,))
        await con.commit()
        recent = await repo.distinct_recent_stock_ids(con, u["id"], "2026-06-07T00:00:00Z")
        old_ok = await repo.distinct_recent_stock_ids(con, u["id"], "2025-12-01T00:00:00Z")
    assert recent == [] and old_ok == [s.id]
