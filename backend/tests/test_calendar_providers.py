import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.calendar.providers.seed_provider import SeedProvider
from app.calendar.providers.fred_provider import FredProvider, parse_fred
from app.calendar.providers.finnhub_calendar_provider import (
    FinnhubCalendarProvider, parse_earnings)
from app.calendar.providers import investing_provider as inv

CFG = str(Path(__file__).resolve().parents[2] / "config")
CASSETTE = Path(__file__).resolve().parent / "cassettes" / "investing_calendar.json"
START = datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc)


# --- Seed provider (real config dates) ---

@pytest.mark.asyncio
async def test_seed_provider_returns_in_range_events():
    evs = await SeedProvider(CFG).fetch_scheduled(START, END)
    etypes = {e.extra["event_type"] for e in evs}
    assert "us_fomc_rate_decision" in etypes      # FOMC 2026-06-17 is in range
    # the real BOK/BOJ June dates: BOJ 2026-06-16 in range; all carry tz-aware UTC
    assert all(e.scheduled_utc.tzinfo is not None for e in evs)


@pytest.mark.asyncio
async def test_seed_provider_filters_out_of_range():
    narrow = await SeedProvider(CFG).fetch_scheduled(
        datetime(2026, 6, 17, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 17, 23, 0, tzinfo=timezone.utc))
    ids = {e.provider_event_id for e in narrow}
    assert ids == {"fomc-2026-06-17"}             # only the FOMC decision that day
    assert next(iter(narrow)).time_estimated is False


@pytest.mark.asyncio
async def test_seed_provider_marks_estimated_times():
    evs = await SeedProvider(CFG).fetch_scheduled(START, END)
    boj = [e for e in evs if e.extra["event_type"] == "jp_boj_rate_decision"]
    assert boj and all(e.time_estimated for e in boj)   # BOJ time is an estimate


# --- FRED parser (shape fixture; live test below) ---

def test_parse_fred_maps_releases():
    data = {"release_dates": [
        {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-06-17"},
        {"release_id": 53, "release_name": "Gross Domestic Product", "date": "2026-06-25"},
    ]}
    evs = parse_fred(data, START, END)
    assert len(evs) == 2
    assert evs[0].provider == "fred" and evs[0].raw_name == "Consumer Price Index"
    assert evs[0].scheduled_utc == datetime(2026, 6, 17, 12, 30, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_fred_no_key_returns_empty():
    assert await FredProvider("").fetch_scheduled(START, END) == []


# --- Finnhub earnings parser (shape fixture; live test below) ---

def test_parse_earnings_maps_rows():
    data = {"earningsCalendar": [
        {"symbol": "NVDA", "date": "2026-06-17", "epsEstimate": 1.2, "epsActual": None,
         "revenueEstimate": 5e10, "hour": "amc", "quarter": 2, "year": 2026},
    ]}
    evs = parse_earnings(data, START, END)
    assert len(evs) == 1
    e = evs[0]
    assert e.extra["kind"] == "earnings" and e.extra["symbol"] == "NVDA"
    assert e.scheduled_utc.hour == 21 and e.forecast == 1.2


@pytest.mark.asyncio
async def test_finnhub_no_key_returns_empty():
    assert await FinnhubCalendarProvider("").fetch_scheduled(START, END) == []


# --- Investing.com parser against the REAL captured cassette ---

def test_investing_parser_on_real_cassette():
    payload = json.loads(CASSETTE.read_text(encoding="utf-8"))
    offset = int((payload.get("params") or {}).get("offsetSec", 0))
    events = inv.parse_rows(payload["data"], offset)
    assert len(events) > 0
    for e in events[:20]:
        assert e.provider == "investing_com"
        assert e.scheduled_utc.tzinfo is not None
        assert e.raw_name
        assert e.importance in (None, 1, 2, 3)
    # at least one US event present in a mid-June 2026 window
    assert any(e.country == "US" for e in events)


# --- Live (real network), excluded by default ---

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_investing_fetch():
    evs = await inv.InvestingProvider().fetch_scheduled(
        datetime(2026, 6, 16, tzinfo=timezone.utc), datetime(2026, 6, 19, tzinfo=timezone.utc))
    assert len(evs) > 0 and all(e.scheduled_utc.tzinfo is not None for e in evs)
