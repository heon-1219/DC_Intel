from datetime import datetime, timezone
from pathlib import Path

from app.calendar import registry as reg
from app.calendar.canonicalize import canonicalize
from app.calendar.impact import assign_impact
from app.calendar.affected import build_affected_json
from app.calendar.models import RawEvent

CFG = str(Path(__file__).resolve().parents[2] / "config")
REG = str(Path(CFG) / "economic_events.yaml")
SEC = str(Path(CFG) / "sectors.yaml")
REGISTRY = reg.load_registry(REG)
SECTORS = reg.load_sectors(SEC)
MEGA = reg.load_mega_caps(REG)
T = datetime(2026, 6, 17, 18, 0, tzinfo=timezone.utc)


def test_assign_impact_precedence():
    assert assign_impact({"impact_override": "high"}, 1) == ("high", "override")
    assert assign_impact({}, 3) == ("high", "provider")
    assert assign_impact({}, 2) == ("medium", "provider")
    assert assign_impact(None, None) == ("low", "default")


def test_build_affected_macro_and_earnings():
    cpi = REGISTRY["us_cpi"]
    a = build_affected_json(cpi, SECTORS)
    assert a["scope"] == "macro" and "KOSPI" in a["indexes"] and a["history"] is None
    e = build_affected_json(None, SECTORS, earnings_stock=("NVDA", "NASDAQ"))
    assert e["scope"] == "stock"
    assert e["stocks"][0]["symbol"] == "NVDA"
    assert {"code": "semiconductors"} in e["sectors"]


def test_canonicalize_investing_cpi():
    raw = RawEvent("investing_com", "550877", "CPI (YoY)", "US", T, importance=3,
                   forecast=2.6, previous=2.7)
    ce = canonicalize(raw, REGISTRY, SECTORS, MEGA)
    assert ce.event_type == "us_cpi"
    assert ce.impact_level == "high" and ce.impact_source == "override"
    assert ce.event_name == "US Consumer Prices (CPI)"
    assert ce.title_ko == "미국 소비자물가지수(CPI)"
    assert ce.event_time == "2026-06-17T18:00:00Z"
    assert ce.affected_json["scope"] == "macro"


def test_canonicalize_unmatched_autoslugs():
    raw = RawEvent("investing_com", "99", "Mystery Print (MoM)", "US", T, importance=2)
    ce = canonicalize(raw, REGISTRY, SECTORS, MEGA)
    assert ce.event_type == "us_mystery_print_mom"
    assert ce.impact_level == "medium" and ce.impact_source == "provider"  # provider bulls
    assert ce.title_ko is None


def test_canonicalize_earnings_megacap_vs_other():
    nv = RawEvent("finnhub", "earnings:NVDA:2026-06-17", "NVDA earnings", "US", T,
                  extra={"kind": "earnings", "symbol": "NVDA", "exchange": "NASDAQ"})
    ce = canonicalize(nv, REGISTRY, SECTORS, MEGA)
    assert ce.event_type == "earnings:NVDA:NASDAQ"
    assert ce.impact_level == "high"            # mega-cap
    other = RawEvent("finnhub", "earnings:ZZZ:2026-06-17", "ZZZ earnings", "US", T,
                     extra={"kind": "earnings", "symbol": "ZZZ", "exchange": "NASDAQ"})
    assert canonicalize(other, REGISTRY, SECTORS, MEGA).impact_level == "medium"


def test_canonicalize_country_guard_rejects_mismatched_alias():
    # A non-KR event must NOT canonicalize to kr_* even if a name alias would match.
    raw = RawEvent("investing_com", "9", "BoK Interest Rate Decision", "JP", T, importance=3)
    ce = canonicalize(raw, REGISTRY, SECTORS, MEGA)
    assert not ce.event_type.startswith("kr_")          # country guard kicked in
    assert ce.event_type == "jp_bok_interest_rate_decision"   # auto-slugged under JP


def test_canonicalize_seed_uses_event_type_from_extra():
    raw = RawEvent("seed", "fomc-2026-06-17", "Fed Interest Rate Decision", "US", T,
                   time_estimated=False, extra={"event_type": "us_fomc_rate_decision"})
    ce = canonicalize(raw, REGISTRY, SECTORS, MEGA)
    assert ce.event_type == "us_fomc_rate_decision"
    assert ce.impact_level == "high" and ce.impact_source == "override"
    assert "KOSPI" in ce.affected_json["indexes"]
