from datetime import datetime, timezone

from app.calendar.actuals import build_avf, compute_surprise
from app.calendar.models import RawEvent

T = datetime(2026, 6, 17, 12, 30, tzinfo=timezone.utc)


def test_compute_surprise_cpi_below_forecast_bullish():
    s, d, read = compute_surprise(2.4, 2.6, 0.05, -1)   # CPI polarity -1
    assert s == -0.2 and d == "below_forecast" and read == "bullish"


def test_compute_surprise_in_line_neutral():
    _, d, read = compute_surprise(2.62, 2.6, 0.05, -1)
    assert d == "in_line" and read == "neutral"


def test_compute_surprise_missing_returns_none():
    assert compute_surprise(None, 2.6, 0.0, -1) == (None, None, None)


def test_build_avf_earnings_beat_is_bullish():
    raw = RawEvent("finnhub", "x", "NVDA earnings", "US", T, forecast=4.12, actual=4.40,
                   extra={"kind": "earnings", "symbol": "NVDA"})
    avf = build_avf(raw, None, "finnhub", released_at="2026-06-17T21:00:00Z")
    m = avf["metrics"][0]
    assert m["key"] == "eps" and m["surprise_direction"] == "above_forecast"
    assert avf["market_read"] == "bullish" and avf["released_at_utc"] == "2026-06-17T21:00:00Z"


def test_build_avf_scheduled_has_null_read_and_release():
    entry = {"surprise_polarity": -1, "neutral_band_abs": 0.05,
             "titles": {"en": "US CPI", "ko": "미국 CPI"}}
    raw = RawEvent("investing_com", "x", "CPI (YoY)", "US", T, forecast=2.6, previous=2.7)
    avf = build_avf(raw, entry, "investing_com")
    assert avf["market_read"] is None and avf["released_at_utc"] is None
    assert avf["metrics"][0]["forecast"] == 2.6 and avf["metrics"][0]["actual"] is None


def test_build_avf_none_for_dataless_event():
    raw = RawEvent("investing_com", "x", "Fed Chair Speech", "US", T)
    assert build_avf(raw, None, "investing_com") is None
