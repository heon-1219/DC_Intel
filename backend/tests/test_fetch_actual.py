from datetime import datetime, timezone
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.calendar import registry as reg
from app.calendar.canonicalize import canonicalize
from app.calendar.models import RawEvent
from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import economic_events as repo
from app.jobs.fetch_actual import backfill_actuals
from app.providers.breaker import CircuitBreaker
from tests._fakes import FakeCalendarProvider

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CFG = str(Path(__file__).resolve().parents[2] / "config")
REG = str(Path(CFG) / "economic_events.yaml")
SEC = str(Path(CFG) / "sectors.yaml")
REGISTRY = reg.load_registry(REG)
SECTORS = reg.load_sectors(SEC)
MEGA = reg.load_mega_caps(REG)
NOW = datetime(2026, 6, 16, tzinfo=timezone.utc)
SCHED = datetime(2026, 6, 15, 12, 30, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_backfill_fills_actual_and_releases(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)

    pending = canonicalize(
        RawEvent("investing_com", "1", "CPI (YoY)", "US", SCHED, importance=3, forecast=2.6),
        REGISTRY, SECTORS, MEGA)
    async with connect(db) as con:
        await repo.upsert_event(con, pending)

    with_actual = FakeCalendarProvider("investing_calendar", events=[
        RawEvent("investing_com", "1", "CPI (YoY)", "US", SCHED, importance=3,
                 forecast=2.6, actual=2.4)])
    updated = await backfill_actuals(db, r, cb, providers=[with_actual], registry_path=REG,
                                     sectors_path=SEC, now=NOW)
    assert updated == 1
    async with connect(db) as con:
        rows = await repo.list_in_range(con, "2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z")
    import json
    cpi = rows[0]
    assert cpi["status"] == "released"
    avf = json.loads(cpi["actual_vs_forecast_json"])
    assert avf["metrics"][0]["actual"] == 2.4 and avf["market_read"] == "bullish"


@pytest.mark.asyncio
async def test_backfill_noop_when_actual_still_absent(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    pending = canonicalize(
        RawEvent("investing_com", "2", "CPI (YoY)", "US", SCHED, importance=3, forecast=2.6),
        REGISTRY, SECTORS, MEGA)
    async with connect(db) as con:
        await repo.upsert_event(con, pending)
    still_pending = FakeCalendarProvider("investing_calendar", events=[
        RawEvent("investing_com", "2", "CPI (YoY)", "US", SCHED, importance=3, forecast=2.6)])
    updated = await backfill_actuals(db, r, cb, providers=[still_pending], registry_path=REG,
                                     sectors_path=SEC, now=NOW)
    assert updated == 0
