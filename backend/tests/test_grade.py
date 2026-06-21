"""M7c grade_prediction (win-loss §4-§5.3, §7). Strict 3-class grading on the SNAPSHOTTED band;
split-suspect park; high-impact event overlap."""
import json
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as srepo
from app.db.seed import seed_stocks
from app.tracking.grade import grade_prediction, relevant_countries

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


async def _ctx(tmp_path, symbol="005930", exchange="KRX"):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, symbol, exchange)
    return db, ref


def _due(direction="up", entry=100.0, band=0.5, created="2026-06-16T00:00:00Z"):
    return {"id": 1, "stock_id": 1, "timeframe": "5d", "direction": direction,
            "window_closes_at": "2026-06-21T00:00:00Z", "created_at": created,
            "reasoning_json": json.dumps({"entry_price": entry, "neutral_band_pct": band})}


async def _ins_event(con, *, time, country, impact="high"):
    await con.execute(
        "INSERT INTO economic_events (event_name, event_time, impact_level, country, event_type, "
        "provider, status) VALUES (?,?,?,?,?,?,?)",
        ("EVT", time, impact, country, "etype", "seed", "scheduled"))
    await con.commit()


def test_relevant_countries():
    assert relevant_countries("KRX") == ["KR", "US"]
    assert relevant_countries("NASDAQ") == ["US"] and relevant_countries("NYSE") == ["US"]


@pytest.mark.asyncio
async def test_move_pct_up_correct(tmp_path):
    db, ref = await _ctx(tmp_path)
    async with connect(db) as con:
        res = await grade_prediction(con, ref, _due(direction="up"), 102.0, "2026-06-21T01:00:00Z")
    o = res["outcome"]
    assert res["action"] == "grade"
    assert o["actual_price_change_percent"] == pytest.approx(2.0)
    assert o["actual_direction"] == "up" and o["marked_correct"] == 1


@pytest.mark.asyncio
async def test_uses_snapshotted_band_not_config(tmp_path):
    db, ref = await _ctx(tmp_path)
    async with connect(db) as con:
        # +0.3% move: with a wide snapshot band 0.40 -> neutral; with a tight band 0.10 -> up
        wide = await grade_prediction(con, ref, _due(direction="up", band=0.40), 100.3, "2026-06-21T01:00:00Z")
        tight = await grade_prediction(con, ref, _due(direction="up", band=0.10), 100.3, "2026-06-21T01:00:00Z")
    assert wide["outcome"]["actual_direction"] == "neutral" and wide["outcome"]["marked_correct"] == 0
    assert tight["outcome"]["actual_direction"] == "up" and tight["outcome"]["marked_correct"] == 1


@pytest.mark.asyncio
async def test_directional_call_realized_neutral_is_loss(tmp_path):
    db, ref = await _ctx(tmp_path)
    async with connect(db) as con:   # §4.3 worked example: up call, +0.3%, band 0.40 -> neutral -> loss
        res = await grade_prediction(con, ref, _due(direction="up", band=0.40), 100.3, "2026-06-21T01:00:00Z")
    assert res["outcome"]["actual_direction"] == "neutral" and res["outcome"]["marked_correct"] == 0


@pytest.mark.asyncio
async def test_neutral_call_inside_band_is_correct(tmp_path):
    db, ref = await _ctx(tmp_path)
    async with connect(db) as con:
        res = await grade_prediction(con, ref, _due(direction="neutral", band=0.5), 100.1, "2026-06-21T01:00:00Z")
    assert res["outcome"]["actual_direction"] == "neutral" and res["outcome"]["marked_correct"] == 1


@pytest.mark.asyncio
async def test_split_suspect_parks(tmp_path):
    db, ref = await _ctx(tmp_path)
    async with connect(db) as con:
        res = await grade_prediction(con, ref, _due(), 200.0, "2026-06-21T01:00:00Z")   # +100%
    assert res["action"] == "park" and res["reason"] == "split_suspect"


@pytest.mark.asyncio
async def test_event_overlap_country_scoped(tmp_path):
    db, ref = await _ctx(tmp_path, "005930", "KRX")     # relevant {KR, US}
    async with connect(db) as con:
        await _ins_event(con, time="2026-06-18T00:00:00Z", country="US")    # in [created, now], US relevant
        res = await grade_prediction(con, ref, _due(), 101.0, "2026-06-21T01:00:00Z")
    assert res["outcome"]["high_impact_event_overlap"] == 1


@pytest.mark.asyncio
async def test_event_overlap_zero_when_irrelevant_country(tmp_path):
    db, ref = await _ctx(tmp_path, "AAPL", "NASDAQ")    # relevant {US} only
    async with connect(db) as con:
        await _ins_event(con, time="2026-06-18T00:00:00Z", country="KR")    # KR not relevant for a US stock
        res = await grade_prediction(con, ref, _due(), 101.0, "2026-06-21T01:00:00Z")
    assert res["outcome"]["high_impact_event_overlap"] == 0
