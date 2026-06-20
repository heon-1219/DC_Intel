import pytest

from app.ml.config import FEATURE_GROUP, FEATURE_NAMES, TIMEFRAMES, load_ml_config
from app.tracking.labels import DEAD_BAND_PCT, HORIZON_BARS, derive_direction


@pytest.mark.parametrize("change,band,expected", [
    (0.5, 0.4, "up"), (-0.5, 0.4, "down"), (0.1, 0.4, "neutral"),
    (0.4, 0.4, "neutral"), (-0.4, 0.4, "neutral"),   # strict: exactly at band -> neutral
])
def test_derive_direction(change, band, expected):
    assert derive_direction(change, band) == expected


def test_dead_bands_per_timeframe():
    assert DEAD_BAND_PCT == {"1h": 0.15, "5h": 0.30, "24h": 0.40,
                             "2d": 0.50, "3d": 0.60, "5d": 0.75}
    assert set(DEAD_BAND_PCT) == set(TIMEFRAMES)


def test_horizon_bars_for_bar_count_timeframes():
    # bar-count window step per tf (24h is wall-clock, intentionally absent).
    assert HORIZON_BARS == {"1h": 12, "5h": 20, "2d": 2, "3d": 3, "5d": 5}
    assert "24h" not in HORIZON_BARS


def test_feature_contract():
    assert len(FEATURE_NAMES) == 15
    assert FEATURE_NAMES[0] == "rsi_14" and FEATURE_NAMES[-1] == "market_is_krx"
    assert FEATURE_GROUP["market_is_krx"] is None        # aux, no group
    assert FEATURE_GROUP["sent_agg"] == "sentiment"
    groups = {g for g in FEATURE_GROUP.values() if g}
    assert groups == {"rsi", "ema", "macd", "bollinger", "volume",
                      "sentiment", "econ_event", "cross_market"}


def test_ml_config_loads():
    cfg = load_ml_config()
    assert cfg["ship_gate"] == {"win_rate_pct": 52, "coverage_pct": 30}
    assert cfg["tau_dir"]["24h"] == 0.45
    assert cfg["staleness_confidence_cap"] == 65
    assert cfg["dead_band_pct"]["24h"] == 0.40       # sourced from labels.py
    assert cfg["bar_interval"]["1h"] == "5m"
