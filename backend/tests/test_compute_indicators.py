import numpy as np
import pandas as pd
import pytest

from app.services import indicators as ind


def _frame(n=260, start=100.0, step=0.2, vol=100000.0):
    """A clean rising OHLCV frame long enough to converge EMA200. Volume varies slightly
    (non-zero rolling std) so the flat-volume stale_price flag does not fire here."""
    close = pd.Series([start + step * i for i in range(n)])
    volume = pd.Series([vol + (i % 7) * 137.0 for i in range(n)])
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": close.values, "high": (close + 0.1).values,
        "low": (close - 0.1).values, "close": close.values,
        "volume": volume.values,
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


def test_payload_stores_full_precision_not_rounded():
    # §2 — stored at full float precision; rounding is the display layer's job only.
    # A non-round-number close series should leave many-decimal stored values.
    n = 260
    close = pd.Series([100.0 + 0.137 * i for i in range(n)])
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    frame = pd.DataFrame({"open": close.values, "high": (close + 0.1).values,
                          "low": (close - 0.1).values, "close": close.values,
                          "volume": [100000.0 + (i % 5) for i in range(n)]}, index=idx)
    payload = ind.compute_indicators(frame, bar_interval="1d")
    # ema_20 must not equal its 6-decimal rounding (i.e. it carries full precision)
    assert payload["ema_20"] != round(payload["ema_20"], 6)


def test_payload_squeeze_available_at_140_raw_bars():
    # §7.3 — squeeze defined once 140 RAW bars exist (120 window + 20 seed), not 159.
    assert ind.compute_indicators(_frame(n=139), bar_interval="1d")["bb_squeeze"] is None
    assert ind.compute_indicators(_frame(n=140), bar_interval="1d")["bb_squeeze"] is not None


def _squeeze_then_breakout_frame(n=160):
    """A long tight range (low, ~constant bandwidth -> squeeze) ending in a bar that
    breaks far above the upper band -> breakout ending a squeeze (§7.3/§7.4)."""
    base = [100.0 + (0.01 if i % 2 == 0 else -0.01) for i in range(n - 1)]
    closes = base + [108.0]
    close = pd.Series(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": close.values, "high": (close + 0.001).values,
        "low": (close - 0.001).values, "close": close.values,
        "volume": [100000.0 + (i % 7) * 137.0 for i in range(n)],
    }, index=idx)


def test_payload_squeeze_breakout_up_state():
    payload = ind.compute_indicators(_squeeze_then_breakout_frame(), bar_interval="1d")
    assert payload["bb_state"] == "squeeze_breakout_up"


def test_payload_stale_price_on_flat_volume_with_moving_prices():
    # §7A.1 — 20 identical volumes (VolStd=0) flag stale_price even when prices move.
    frame = _frame(n=40)
    frame["volume"] = 100000.0           # constant -> rolling std 0
    payload = ind.compute_indicators(frame, bar_interval="1d")
    assert payload["vol_z20"] == 0.0
    assert "stale_price" in payload["flags"]
    assert "limit_lock" not in payload["flags"]   # high != low, so not a limit lock
