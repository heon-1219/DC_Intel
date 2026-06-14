import numpy as np
import pandas as pd
import pytest

from app.services import indicators as ind


@pytest.mark.parametrize("rsi,expected", [
    (75, "overbought"), (70, "overbought"),
    (65, "bullish"), (60, "bullish"),
    (50, "neutral"), (40, "neutral"),
    (35, "bearish"), (30.1, "bearish"),
    (30, "oversold"), (10, "oversold"),
])
def test_rsi_state(rsi, expected):
    assert ind.rsi_state(rsi) == expected


@pytest.mark.parametrize("z,first_bar,expected", [
    (2.5, False, "surge"), (2.0, False, "surge"),
    (1.5, False, "elevated"), (1.0, False, "elevated"),
    (0.0, False, "normal"), (-0.5, False, "normal"),
    (-1.0, False, "quiet"), (-2.0, False, "quiet"),
    (2.5, True, "elevated"),   # session-open guard raises surge threshold to 3.0
    (3.0, True, "surge"),
])
def test_vol_state(z, first_bar, expected):
    assert ind.vol_state(z, first_bar_of_session=first_bar) == expected


def test_macd_state_priority_cross_over_histogram():
    # A bullish signal-line cross within 3 bars beats a histogram state.
    state = ind.macd_state(cross_dir=1, bars_since_cross=1,
                           zero_cross_dir=0, bars_since_zero_cross=20,
                           hist=pd.Series([0.1, 0.2, 0.3, 0.4]))
    assert state == "bullish_cross"


def test_macd_state_zero_cross_when_no_signal_cross():
    state = ind.macd_state(cross_dir=0, bars_since_cross=20,
                           zero_cross_dir=1, bars_since_zero_cross=2,
                           hist=pd.Series([0.1, 0.2, 0.3, 0.4]))
    assert state == "zero_cross_up"


def test_macd_state_momentum_building():
    state = ind.macd_state(cross_dir=0, bars_since_cross=20,
                           zero_cross_dir=0, bars_since_zero_cross=20,
                           hist=pd.Series([0.1, 0.2, 0.3, 0.4]))
    assert state == "momentum_building"


def test_macd_state_momentum_fading():
    state = ind.macd_state(cross_dir=0, bars_since_cross=20,
                           zero_cross_dir=0, bars_since_zero_cross=20,
                           hist=pd.Series([0.4, 0.3, 0.2, 0.1]))
    assert state == "momentum_fading"


def test_macd_state_neutral():
    state = ind.macd_state(cross_dir=0, bars_since_cross=20,
                           zero_cross_dir=0, bars_since_zero_cross=20,
                           hist=pd.Series([0.1, 0.3, 0.2, 0.25]))
    assert state == "neutral"


def test_bollinger_state_breakout_up():
    pct_b = pd.Series([0.5, 0.6, 1.2])      # last pokes above upper; prior inside
    bw = pd.Series([0.1, 0.1, 0.1])
    assert ind.bollinger_state(pct_b, bw) == "breakout_up"


def test_bollinger_state_riding_upper():
    pct_b = pd.Series([0.96, 0.97, 0.98])   # >=0.95 for 3 consecutive, no fresh breakout
    bw = pd.Series([0.1, 0.1, 0.1])
    assert ind.bollinger_state(pct_b, bw) == "riding_upper"


def test_bollinger_state_inside():
    pct_b = pd.Series([0.4, 0.5, 0.6])
    bw = pd.Series([0.1, 0.1, 0.1])
    assert ind.bollinger_state(pct_b, bw) == "inside"


def test_bollinger_squeeze_true_when_lowest_in_120():
    bw = pd.Series(np.linspace(0.5, 0.05, 140))   # last is the lowest in the trailing 120
    assert ind.bollinger_squeeze(bw) is True


def test_bollinger_squeeze_undefined_with_short_history():
    bw = pd.Series([0.1] * 100)                    # < 140 bars -> None
    assert ind.bollinger_squeeze(bw) is None


def test_ema_stack_flags():
    assert ind.ema_stack(5, 4, 3, 2) == (True, False)   # bullish stack
    assert ind.ema_stack(2, 3, 4, 5) == (False, True)   # bearish stack
    assert ind.ema_stack(5, 3, 4, 2) == (False, False)  # mixed
