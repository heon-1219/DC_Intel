from datetime import datetime, timedelta, timezone

import pytest

import app.cache.redis as cache_redis
from app.calendar.models import CanonEvent, RawEvent
from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import economic_events as repo


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _mk(event_type, when, impact, pid, country="US", avf=None):
    raw = RawEvent("investing_com", pid, "x", country, when)
    return CanonEvent(
        event_type=event_type, event_name=f"{event_type} title", title_ko="제목",
        country=country, event_time=_iso(when), impact_level=impact, impact_source="override",
        provider="investing_com", provider_event_id=pid,
        affected_json={"scope": "macro", "indexes": ["SP500"], "sectors": [], "stocks": [],
                       "history": None}, raw=raw, actual_vs_forecast=avf)


@pytest.mark.asyncio
async def test_calendar_endpoint_returns_events_anonymous(app_client):
    s = get_settings()
    now = datetime.now(timezone.utc)
    async with connect(s.sqlite_path) as con:
        await repo.upsert_event(con, _mk("us_fomc_rate_decision", now + timedelta(days=2),
                                         "high", "f1"))
        await repo.upsert_event(con, _mk("us_cpi", now - timedelta(hours=2), "high", "p1"))
        rows = await repo.list_in_range(con, _iso(now - timedelta(days=1)),
                                        _iso(now + timedelta(days=8)))
        cpi_id = next(r["id"] for r in rows if r["event_type"] == "us_cpi")
        await repo.set_actual(con, cpi_id, {
            "metrics": [{"key": "cpi", "label_en": "CPI", "label_ko": "CPI", "unit": "%",
                         "primary": True, "forecast": 2.6, "previous": 2.7,
                         "revised_previous": None, "actual": 2.4, "surprise_abs": -0.2,
                         "surprise_direction": "below_forecast"}],
            "released_at_utc": _iso(now), "source": "investing_com",
            "surprise_polarity": -1, "market_read": "bullish"})
    await cache_redis.get_client().set("cal:last_synced_at", _iso(now))

    async with app_client as c:
        resp = await c.get("/dashboard/economic-calendar?days=7")
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["data_stale"] is False
    assert {e["event_type"] for e in d["events"]} >= {"us_fomc_rate_decision", "us_cpi"}

    fomc = next(e for e in d["events"] if e["event_type"] == "us_fomc_rate_decision")
    assert fomc["countdown_seconds"] > 0
    assert fomc["affects_your_stocks"] is None and fomc["match_level"] is None
    assert fomc["plain_summary_en"]   # enriched from the registry
    assert fomc["title_en"] == "us_fomc_rate_decision title"   # serialized from event_name

    cpi = next(e for e in d["events"] if e["event_type"] == "us_cpi")
    assert cpi["status"] == "released" and cpi["countdown_seconds"] is None
    assert cpi["actual_vs_forecast"]["market_read"] == "bullish"


@pytest.mark.asyncio
async def test_calendar_endpoint_validates_params(app_client):
    async with app_client as c:
        r1 = await c.get("/dashboard/economic-calendar?days=99")
        r2 = await c.get("/dashboard/economic-calendar?impact=bogus")
        r3 = await c.get("/dashboard/economic-calendar?include_past_hours=999")
    assert r1.status_code == 400 and r2.status_code == 400 and r3.status_code == 400


@pytest.mark.asyncio
async def test_calendar_endpoint_impact_filter(app_client):
    s = get_settings()
    now = datetime.now(timezone.utc)
    async with connect(s.sqlite_path) as con:
        await repo.upsert_event(con, _mk("us_cpi", now + timedelta(days=1), "high", "h1"))
        await repo.upsert_event(con, _mk("us_retail_sales", now + timedelta(days=1),
                                         "medium", "m1"))
    async with app_client as c:
        resp = await c.get("/dashboard/economic-calendar?days=7&impact=high")
    d = resp.json()["data"]
    assert {e["event_type"] for e in d["events"]} == {"us_cpi"}
