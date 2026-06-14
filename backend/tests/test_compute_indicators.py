import numpy as np
import pandas as pd
import pytest

from app.services import indicators as ind


def _frame(n=260, start=100.0, step=0.2, vol=100000.0):
    """A clean rising OHLCV frame long enough to converge EMA200."""
    close = pd.Series([start + step * i for i in range(n)])
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": close.values, "high": (close + 0.1).values,
        "low": (close - 0.1).values, "close": close.values,
        "volume": [vol] * n,
    }, index=idx)


def test_payload_has_full_contract_keys():
    payload = ind.compute_indicators(_frame(), bar_interval="1d")
    for key in ["rsi_14", "rsi_state", "ema_5", "ema_20", "ema_50", "ema_200",
                "ema_200_available", "warming_up", "ema_5_20_cross_dir",
                "bars_since_ema_5_20_cross", "ema_50_200_cross_dir",
                "bars_since_ema_50_200_cross", "price_vs_ema20_pct", "price_vs_ema50_pct",
                "price_vs_ema200_pct", "ema_stack_bullish", "ema_stack_bearish",
                "macd_line", "macd_signal", "macd_histogram", "macd_hist_delta",
                "macd_line_pct", "macd_state", "bars_since_macd_cross", "bb_middle",
                "bb_upper", "bb_lower", "bb_percent_b", "bb_bandwidth", "bb_state",
                "bb_squeeze", "vol_z20", "vol_state", "flags"]:
        assert key in payload, f"missing {key}"


def test_payload_rising_series_is_bullish():
    payload = ind.compute_indicators(_frame(), bar_interval="1d")
    assert payload["rsi_14"] == pytest.approx(100.0, abs=1e-6)   # strictly rising
    assert payload["ema_stack_bullish"] is True
    assert payload["price_vs_ema200_pct"] > 0
    assert payload["ema_200_available"] is True


def test_payload_short_history_drops_ema200_and_flags():
    payload = ind.compute_indicators(_frame(n=120), bar_interval="1d")
    assert payload["ema_200"] is None
    assert payload["ema_200_available"] is False


def test_payload_insufficient_history_flag():
    payload = ind.compute_indicators(_frame(n=10), bar_interval="1d")
    assert payload["vol_z20"] is None
    assert "insufficient_history" in payload["flags"]


def test_payload_warming_up_flag_between_200_and_600():
    payload = ind.compute_indicators(_frame(n=300), bar_interval="1d")
    assert payload["ema_200"] is not None       # computed
    assert payload["warming_up"] is True        # but < 3*200 bars -> warming_up
    assert "warming_up" in payload["flags"]


def test_payload_json_serializable():
    import json
    payload = ind.compute_indicators(_frame(), bar_interval="1d")
    json.dumps(payload)   # must not raise (no numpy scalars / NaN leakage)
