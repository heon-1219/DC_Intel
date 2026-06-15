from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.calendar.models import CanonEvent, RawEvent
from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import economic_events as repo

MIG = str(Path(__file__).resolve().parents[1] / "migrations")


def _canon(event_type="us_cpi", event_time="2026-06-17T12:30:00Z",
           provider="investing_com", pid="ev1", impact="high", country="US"):
    ts = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
    raw = RawEvent(provider, pid, "CPI (YoY)", country, ts, forecast=2.6)
    return CanonEvent(
        event_type=event_type, event_name="US CPI", title_ko="미국 CPI", country=country,
        event_time=event_time, impact_level=impact, impact_source="override",
        provider=provider, provider_event_id=pid,
        affected_json={"scope": "macro", "indexes": ["SP500"], "sectors": [], "stocks": [],
                       "history": None}, raw=raw)


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    return db


@pytest.mark.asyncio
async def test_upsert_by_provider_id_overwrites(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_event(con, _canon(impact="high"))
        await repo.upsert_event(con, _canon(impact="medium"))   # same (provider, pid)
        rows = await repo.list_in_range(con, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    assert len(rows) == 1
    assert rows[0]["impact_level"] == "medium"
    assert rows[0]["title_ko"] == "미국 CPI"


@pytest.mark.asyncio
async def test_upsert_by_type_time_when_no_provider_id(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_event(con, _canon(provider="seed", pid=None))
        await repo.upsert_event(con, _canon(provider="seed", pid=None, impact="low"))
        rows = await repo.list_in_range(con, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    assert len(rows) == 1   # collapsed on (event_type, event_time)
    assert rows[0]["impact_level"] == "low"


@pytest.mark.asyncio
async def test_list_in_range_filters(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_event(con, _canon(event_type="us_cpi", pid="a", impact="high",
                                            country="US"))
        await repo.upsert_event(con, _canon(event_type="kr_cpi", pid="b", impact="medium",
                                            country="KR"))
        hi = await repo.list_in_range(con, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z",
                                      impact=["high"])
        kr = await repo.list_in_range(con, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z",
                                      country=["KR"])
    assert [r["event_type"] for r in hi] == ["us_cpi"]
    assert [r["event_type"] for r in kr] == ["kr_cpi"]


@pytest.mark.asyncio
async def test_mark_cancelled_excludes_from_list(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_event(con, _canon(pid="x"))
        rows = await repo.list_in_range(con, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
        await repo.mark_cancelled(con, [rows[0]["id"]])
        after = await repo.list_in_range(con, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    assert len(rows) == 1 and after == []
