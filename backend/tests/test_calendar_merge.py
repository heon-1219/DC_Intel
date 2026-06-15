from datetime import datetime, timezone
from pathlib import Path

from app.calendar import registry as reg
from app.calendar.canonicalize import canonicalize
from app.calendar.merge import dedup
from app.calendar.models import RawEvent

CFG = str(Path(__file__).resolve().parents[2] / "config")
REG = str(Path(CFG) / "economic_events.yaml")
SEC = str(Path(CFG) / "sectors.yaml")
REGISTRY = reg.load_registry(REG)
SECTORS = reg.load_sectors(SEC)
MEGA = reg.load_mega_caps(REG)


def _canon(raw):
    return canonicalize(raw, REGISTRY, SECTORS, MEGA)


def test_seed_wins_time_for_central_bank():
    seed_t = datetime(2026, 6, 17, 18, 0, tzinfo=timezone.utc)
    scrape_t = datetime(2026, 6, 17, 18, 5, tzinfo=timezone.utc)   # 5 min off
    seed = _canon(RawEvent("seed", "fomc-2026-06-17", "Fed Interest Rate Decision", "US",
                           seed_t, extra={"event_type": "us_fomc_rate_decision"}))
    scrape = _canon(RawEvent("investing_com", "1", "Fed Interest Rate Decision", "US",
                             scrape_t, importance=3, forecast=3.5))
    merged = dedup([scrape, seed])
    assert len(merged) == 1
    assert merged[0].event_time == "2026-06-17T18:00:00Z"      # seed time wins
    assert merged[0].raw.forecast == 3.5                        # forecast merged from scrape


def test_two_providers_same_cpi_collapse():
    t1 = datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc)
    inv = _canon(RawEvent("investing_com", "2", "CPI (YoY)", "US", t1, importance=3,
                          forecast=2.6))
    fred = _canon(RawEvent("fred", "10:2026-06-11", "Consumer Price Index", "US", t1))
    merged = dedup([fred, inv])
    assert len(merged) == 1
    assert merged[0].provider == "investing_com"   # higher priority than fred
    assert merged[0].raw.forecast == 2.6


def test_distinct_dates_not_merged():
    a = _canon(RawEvent("investing_com", "3", "CPI (YoY)", "US",
                        datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc), importance=3))
    b = _canon(RawEvent("investing_com", "4", "CPI (YoY)", "US",
                        datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc), importance=3))
    assert len(dedup([a, b])) == 2
