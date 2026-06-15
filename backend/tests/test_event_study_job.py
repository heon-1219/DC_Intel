import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from app.calendar import registry as reg
from app.calendar.actuals import build_avf
from app.calendar.canonicalize import canonicalize
from app.calendar.models import RawEvent
from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import economic_events as repo
from app.db.seed import seed_stocks
from app.jobs.event_study import econ_event_study
from tests._fakes import FakeBarProvider

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CFG = str(Path(__file__).resolve().parents[2] / "config")
CSV = str(Path(CFG) / "seed_stocks.csv")
REG = str(Path(CFG) / "economic_events.yaml")
SEC = str(Path(CFG) / "sectors.yaml")
REGISTRY = reg.load_registry(REG)
SECTORS = reg.load_sectors(SEC)
MEGA = reg.load_mega_caps(REG)
NOW = datetime(2026, 6, 16, tzinfo=timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ramp_bars():
    idx = pd.date_range("2026-02-01", "2026-06-01", freq="1h", tz="UTC")
    return pd.DataFrame({"close": [100.0 + 0.5 * i for i in range(len(idx))]}, index=idx)


async def _seed_with_history(db, n_released):
    migrate(db, MIG)
    seed_stocks(db, CSV)
    entry = REGISTRY["us_cpi"]
    months = [(2, 15), (3, 15), (4, 15), (5, 15)][:n_released]
    async with connect(db) as con:
        # upcoming occurrence (affected indexes incl. SP500/NASDAQ_COMPOSITE/KOSPI)
        up = canonicalize(RawEvent("investing_com", "up", "CPI (YoY)", "US",
                                   datetime(2026, 6, 20, 12, 30, tzinfo=timezone.utc),
                                   importance=3, forecast=2.6), REGISTRY, SECTORS, MEGA)
        await repo.upsert_event(con, up)
        # released past occurrences with actuals
        for i, (mo, day) in enumerate(months):
            t = datetime(2026, mo, day, 12, 30, tzinfo=timezone.utc)
            ce = canonicalize(RawEvent("investing_com", f"r{i}", "CPI (YoY)", "US", t,
                                       importance=3, forecast=2.6, actual=2.4),
                              REGISTRY, SECTORS, MEGA)
            await repo.upsert_event(con, ce)
            rows = await repo.list_released_occurrences(con, "us_cpi", "2024-01-01T00:00:00Z")
            # mark this one released with its avf
            avf = build_avf(RawEvent("investing_com", f"r{i}", "CPI (YoY)", "US", t,
                                     forecast=2.6, actual=2.4), entry, "investing_com",
                            released_at=_iso(t))
            cur = await con.execute(
                "SELECT id FROM economic_events WHERE provider_event_id=?", (f"r{i}",))
            eid = (await cur.fetchone())["id"]
            await repo.set_actual(con, eid, avf)
    return db


@pytest.mark.asyncio
async def test_event_study_writes_history_when_enough_occurrences(tmp_path):
    db = await _seed_with_history(str(tmp_path / "t.db"), n_released=4)
    updated = await econ_event_study(db, FakeBarProvider(bars=_ramp_bars()),
                                     registry_path=REG, now=NOW)
    assert updated == 1
    async with connect(db) as con:
        rows = await repo.list_in_range(con, "2026-06-18T00:00:00Z", "2026-06-30T00:00:00Z")
    up = next(r for r in rows if r["event_type"] == "us_cpi")
    hist = json.loads(up["affected_stocks_json"])["history"]
    assert hist["sample_size"] == 4
    targets = {pt["target"] for pt in hist["per_target"]}
    assert "index:SP500" in targets
    assert hist["per_target"][0]["windows"]["1h"]["n"] == 4


@pytest.mark.asyncio
async def test_event_study_skips_when_too_few(tmp_path):
    db = await _seed_with_history(str(tmp_path / "t.db"), n_released=3)   # < min_n
    updated = await econ_event_study(db, FakeBarProvider(bars=_ramp_bars()),
                                     registry_path=REG, now=NOW)
    assert updated == 0
    async with connect(db) as con:
        rows = await repo.list_in_range(con, "2026-06-18T00:00:00Z", "2026-06-30T00:00:00Z")
    up = next(r for r in rows if r["event_type"] == "us_cpi")
    assert json.loads(up["affected_stocks_json"])["history"] is None
