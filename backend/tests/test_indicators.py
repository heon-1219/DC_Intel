import numpy as np
import pandas as pd
import pytest

from app.services import indicators as ind


def test_rsi_wilder_worked_example_seed_bar():
    # technical-indicators.md §4.2 — 15 closes -> RSI 77.8 at the seed bar (bar 14).
    closes = pd.Series([100, 101, 102, 101, 103, 104, 103, 105, 106,
                        105, 107, 108, 107, 109, 110], dtype=float)
    rsi = ind.rsi_wilder(closes)
    assert rsi.iloc[14] == pytest.approx(77.78, abs=0.01)


def test_rsi_wilder_worked_example_next_bar():
    # §4.2 — appending a down bar (close 109) -> RSI 73.4 (Wilder stickiness).
    closes = pd.Series([100, 101, 102, 101, 103, 104, 103, 105, 106,
                        105, 107, 108, 107, 109, 110, 109], dtype=float)
    rsi = ind.rsi_wilder(closes)
    assert rsi.iloc[15] == pytest.approx(73.4, abs=0.05)


def test_rsi_all_gains_is_100():
    closes = pd.Series([float(x) for x in range(1, 20)])  # strictly rising
    rsi = ind.rsi_wilder(closes)
    assert rsi.iloc[-1] == pytest.approx(100.0)


def test_rsi_flat_series_is_50():
    closes = pd.Series([50.0] * 20)
    rsi = ind.rsi_wilder(closes)
    assert rsi.iloc[-1] == pytest.approx(50.0)


def test_ema5_worked_example():
    # §5.2 — EMA5 over 7 closes.
    closes = pd.Series([10, 11, 12, 11, 13, 14, 13], dtype=float)
    e = ind.ema(closes, 5)
    assert e.iloc[4] == pytest.approx(11.40, abs=0.005)   # SMA seed at bar 5
    assert e.iloc[5] == pytest.approx(12.27, abs=0.005)
    assert e.iloc[6] == pytest.approx(12.51, abs=0.005)


def test_ema_undefined_before_seed():
    closes = pd.Series([10, 11, 12], dtype=float)
    e = ind.ema(closes, 5)
    assert e.isna().all()   # fewer than `span` bars -> all NaN


def test_macd_signal_recursion_worked_example():
    # §6.2 — the signal-line EMA9 step: alpha9 = 2/10 = 0.2.
    # Signal_t = 0.2*MACD_t + 0.8*Signal_{t-1} = 0.2*1.40 + 0.8*1.10 = 1.16.
    macd_t, prev_signal = 1.40, 1.10
    alpha9 = 2.0 / (9 + 1)
    signal_t = alpha9 * macd_t + (1 - alpha9) * prev_signal
    assert signal_t == pytest.approx(1.16, abs=1e-9)
    assert macd_t - signal_t == pytest.approx(0.24, abs=1e-9)   # histogram


def test_macd_series_definitions():
    # MACD line == EMA12 - EMA26; signal == EMA9 of the MACD line; hist == line - signal.
    rng = pd.Series(np.linspace(100, 130, 80))  # 80 bars, enough to converge all EMAs
    line, signal, hist = ind.macd(rng)
    expected_line = ind.ema(rng, 12) - ind.ema(rng, 26)
    tail = expected_line.dropna().index[-1]
    assert line.loc[tail] == pytest.approx(expected_line.loc[tail], abs=1e-9)
    assert hist.loc[tail] == pytest.approx(line.loc[tail] - signal.loc[tail], abs=1e-9)


def test_bollinger_matches_documented_formula():
    # §7.1 — population stddev (ddof=0); upper/lower = mid +/- 2*sigma; %B and bandwidth.
    closes = pd.Series(np.concatenate([np.full(19, 50.0), [52.6]]))  # 20 bars, last spikes up
    mid, upper, lower, pct_b, bw = ind.bollinger(closes)
    win = closes.iloc[-20:]
    exp_mid = win.mean()
    exp_sigma = win.std(ddof=0)
    assert mid.iloc[-1] == pytest.approx(exp_mid, abs=1e-9)
    assert upper.iloc[-1] == pytest.approx(exp_mid + 2 * exp_sigma, abs=1e-9)
    assert lower.iloc[-1] == pytest.approx(exp_mid - 2 * exp_sigma, abs=1e-9)
    exp_pctb = (52.6 - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])
    assert pct_b.iloc[-1] == pytest.approx(exp_pctb, abs=1e-9)
    assert bw.iloc[-1] == pytest.approx((upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1], abs=1e-9)
    assert pct_b.iloc[-1] > 1.0   # close above upper band -> breakout territory


def test_bollinger_band_arithmetic_50_sigma_1p2():
    # §7.2 reference arithmetic: mid=50, sigma=1.2 -> upper=52.4; with close=52.6, %B=1.04.
    mid, sigma, close = 50.0, 1.2, 52.6
    upper, lower = mid + 2 * sigma, mid - 2 * sigma
    assert upper == pytest.approx(52.4, abs=1e-9)
    assert (close - lower) / (upper - lower) == pytest.approx(1.0417, abs=0.001)


def test_bollinger_flat_series_percent_b_half():
    closes = pd.Series([50.0] * 20)
    _, _, _, pct_b, bw = ind.bollinger(closes)
    assert pct_b.iloc[-1] == pytest.approx(0.5)   # sigma==0 edge -> %B=0.5
    assert bw.iloc[-1] == pytest.approx(0.0)


def test_vol_z20_worked_example():
    # §7A.2 — current bar trades well above the 20-bar mean; matches the ddof=0 formula.
    vols = pd.Series(np.concatenate([
        np.full(10, 120000.0), np.full(9, 80000.0), [138000.0]]))  # 20 bars
    z = ind.vol_z20(vols)
    win = vols.iloc[-20:]
    exp = (138000.0 - win.mean()) / win.std(ddof=0)
    assert z.iloc[-1] == pytest.approx(exp, abs=1e-9)


def test_vol_z20_clips_to_lower_bound():
    # A near-zero volume bar after a high baseline produces raw z < -3 -> clipped to -3.0.
    # With a 20-bar window the +6 upper bound is mathematically unreachable
    # (max |z| of one outlier in n=20 is (n-1)/sqrt(n) ~ 4.25); both bounds are applied
    # in code per the prediction-model.md §4.2 contract.
    vols = pd.Series(np.concatenate([np.full(19, 100000.0), [0.0]]))
    z = ind.vol_z20(vols)
    assert z.iloc[-1] == pytest.approx(-3.0)


def test_vol_z20_flat_volume_is_zero():
    vols = pd.Series([100.0] * 20)
    z = ind.vol_z20(vols)
    assert z.iloc[-1] == pytest.approx(0.0)   # sigma==0 edge


def test_crossover_up_then_recent():
    fast = pd.Series([1, 2, 3, 4, 9, 10], dtype=float)
    slow = pd.Series([5, 5, 5, 5, 5, 5], dtype=float)
    direction, bars_since = ind.crossover(fast, slow)
    assert direction == 1            # fast crossed above
    assert bars_since == 1           # crossed at index 4, last index 5


def test_crossover_down():
    fast = pd.Series([9, 9, 9, 1], dtype=float)
    slow = pd.Series([5, 5, 5, 5], dtype=float)
    direction, bars_since = ind.crossover(fast, slow)
    assert direction == -1
    assert bars_since == 0           # crossed on the last bar


def test_crossover_none_returns_zero_and_cap():
    fast = pd.Series([9, 9, 9, 9], dtype=float)
    slow = pd.Series([5, 5, 5, 5], dtype=float)
    direction, bars_since = ind.crossover(fast, slow, cap=20)
    assert direction == 0
    assert bars_since == 20           # capped sentinel when no cross in window


def test_crossover_bars_since_capped():
    fast = pd.Series([1] + [9] * 40, dtype=float)   # cross at index 1, 39 bars ago
    slow = pd.Series([5] * 41, dtype=float)
    _, bars_since = ind.crossover(fast, slow, cap=20)
    assert bars_since == 20           # capped at 20
