from datetime import datetime, timezone

import pandas as pd
import pytest

from app.calendar.event_study import aggregate, window_returns


def _bars(closes, start="2026-06-10 13:00"):
    idx = pd.date_range(start, periods=len(closes), freq="1h", tz="UTC")
    return pd.DataFrame({"close": [float(c) for c in closes]}, index=idx)


def test_window_returns_1h_and_24h():
    closes = [100.0, 101.0] + [100.0] * 22 + [103.0]   # 25 hourly bars: 13:00 d1 .. 13:00 d2
    bars = _bars(closes)
    t0 = datetime(2026, 6, 10, 13, 0, tzinfo=timezone.utc)
    r = window_returns(bars, t0)
    assert r["1h"] == 1.0     # 101 vs 100
    assert r["24h"] == 3.0    # last bar within +24h (103) vs 100


def test_window_returns_none_when_no_prior_bar():
    bars = _bars([100.0, 101.0])
    t0 = datetime(2026, 6, 10, 11, 0, tzinfo=timezone.utc)   # before first bar
    assert window_returns(bars, t0) == {"1h": None, "24h": None}


def test_aggregate_consistency_and_surprise_alignment():
    rets = [{"1h": 1.0, "24h": 2.0}, {"1h": 0.5, "24h": -1.0},
            {"1h": -0.8, "24h": 1.5}, {"1h": 1.2, "24h": 0.9}]
    signs = [1, 1, -1, 1]
    h = aggregate(rets, signs)["1h"]
    assert h["n"] == 4
    assert h["direction_consistency"] == 0.75 and h["modal_direction"] == "up"  # 3 up, 1 down
    assert h["surprise_aligned_consistency"] == 1.0   # sign(r)==surprise_sign for all 4
    assert h["avg_abs_move_pct"] == pytest.approx(0.88, abs=0.01)


def test_aggregate_empty_returns_nothing():
    assert aggregate([{"1h": None, "24h": None}], [None]) == {}
