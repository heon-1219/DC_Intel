from pathlib import Path

from app.calendar import registry as reg

CFG = str(Path(__file__).resolve().parents[2] / "config")
REG = str(Path(CFG) / "economic_events.yaml")
SEC = str(Path(CFG) / "sectors.yaml")


def test_registry_loads_core_event_types():
    r = reg.load_registry(REG)
    for et in ["us_cpi", "us_fomc_rate_decision", "kr_bok_rate_decision",
               "jp_boj_rate_decision", "us_nonfarm_payrolls"]:
        assert et in r
    assert len(r) >= 12


def test_mega_caps_loaded():
    caps = reg.load_mega_caps(REG)
    assert "NVDA" in caps and "005930" in caps


def test_match_event_type_canonicalizes_aliases():
    r = reg.load_registry(REG)
    assert reg.match_event_type(r, "investing_com", "CPI (YoY)") == "us_cpi"
    assert reg.match_event_type(r, "investing_com", "core cpi (yoy)") == "us_cpi"  # case-insensitive
    assert reg.match_event_type(r, "fred", "Consumer Price Index") == "us_cpi"
    assert reg.match_event_type(r, "investing_com", "Totally Unknown Event") is None


def test_auto_slug():
    assert reg.auto_slug("US", "Some New Indicator (MoM)") == "us_some_new_indicator_mom"


def test_sectors_and_membership():
    s = reg.load_sectors(SEC)
    assert "semiconductors" in s
    assert "semiconductors" in reg.sector_codes_for(s, "005930", "KRX")
    assert "semiconductors" in reg.sector_codes_for(s, "NVDA", "NASDAQ")
