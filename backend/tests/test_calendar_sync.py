from datetime import datetime, timezone
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.calendar.models import RawEvent
from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import economic_events as repo
from app.jobs.calendar_sync import sync_calendar
from app.providers.breaker import CircuitBreaker
from app.providers.retry import ProviderError
from tests._fakes import FakeCalendarProvider

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CFG = str(Path(__file__).resolve().parents[2] / "config")
REG = str(Path(CFG) / "economic_events.yaml")
SEC = str(Path(CFG) / "sectors.yaml")
NOW = datetime(2026, 6, 16, tzinfo=timezone.utc)

CPI = RawEvent("investing_com", "1", "CPI (YoY)", "US",
               datetime(2026, 6, 17, 12, 30, tzinfo=timezone.utc), importance=3, forecast=2.6)
FOMC = RawEvent("seed", "fomc-2026-06-17", "Fed Interest Rate Decision", "US",
                datetime(2026, 6, 17, 18, 0, tzinfo=timezone.utc),
                extra={"event_type": "us_fomc_rate_decision"})


@pytest.mark.asyncio
async def test_sync_upserts_and_records_failure(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    providers = [
        FakeCalendarProvider("investing_calendar", events=[CPI]),
        FakeCalendarProvider("seed", events=[FOMC]),
        FakeCalendarProvider("finnhub", error=ProviderError("down")),
    ]
    n = await sync_calendar(db, r, cb, providers=providers, registry_path=REG,
                            sectors_path=SEC, now=NOW)
    assert n == 2
    async with connect(db) as con:
        rows = await repo.list_in_range(con, "2026-06-16T00:00:00Z", "2026-06-30T00:00:00Z")
    etypes = {row["event_type"] for row in rows}
    assert {"us_cpi", "us_fomc_rate_decision"} <= etypes
    assert await r.get("cal:last_synced_at") is not None
    assert int(await r.get("cb:finnhub:fails")) >= 1   # dead provider recorded


@pytest.mark.asyncio
async def test_sync_dedups_same_event_from_two_providers(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    fred_cpi = RawEvent("fred", "10:2026-06-17", "Consumer Price Index", "US",
                        datetime(2026, 6, 17, 12, 30, tzinfo=timezone.utc))
    providers = [FakeCalendarProvider("investing_calendar", events=[CPI]),
                 FakeCalendarProvider("fred", events=[fred_cpi])]
    n = await sync_calendar(db, r, cb, providers=providers, registry_path=REG,
                            sectors_path=SEC, now=NOW)
    assert n == 1   # same us_cpi same day collapses
