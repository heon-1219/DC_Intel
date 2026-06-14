"""Pure technical-indicator math. No I/O. Source of truth: docs/technical-indicators.md.

Conventions: bar t = last row; SMA-seeded smoothing (so the doc's worked examples reproduce
at the seed bar); Wilder alpha = 1/period; population stddev (ddof=0) for Bollinger/volume sigma.
"""
import numpy as np
import pandas as pd


# --- Core math -------------------------------------------------------------

def _wilder_smooth(s: pd.Series, period: int) -> pd.Series:
    """SMA seed of the first `period` values (indices 1..period after a .diff()),
    then Wilder recursion avg_t = (avg_{t-1}*(period-1) + s_t)/period."""
    out = pd.Series(np.nan, index=s.index, dtype=float)
    if len(s) <= period:
        return out
    out.iloc[period] = s.iloc[1:period + 1].mean()
    for i in range(period + 1, len(s)):
        out.iloc[i] = (out.iloc[i - 1] * (period - 1) + s.iloc[i]) / period
    return out


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    close = close.astype(float).reset_index(drop=True)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = _wilder_smooth(gain, period)
    avg_loss = _wilder_smooth(loss, period)
    rs = avg_gain / avg_loss
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.mask(avg_loss == 0, 100.0)
    rsi = rsi.mask(avg_gain == 0, 0.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return rsi


def ema(close: pd.Series, span: int) -> pd.Series:
    """SMA-seeded EMA: seed = SMA of the first `span` closes at index span-1, then
    EMA_t = alpha*C_t + (1-alpha)*EMA_{t-1}, alpha = 2/(span+1)."""
    close = close.astype(float).reset_index(drop=True)
    alpha = 2.0 / (span + 1)
    out = pd.Series(np.nan, index=close.index, dtype=float)
    if len(close) < span:
        return out
    out.iloc[span - 1] = close.iloc[:span].mean()
    for i in range(span, len(close)):
        out.iloc[i] = alpha * close.iloc[i] + (1.0 - alpha) * out.iloc[i - 1]
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram), all on `close`'s position index.
    Signal is the SMA-seeded EMA9 of the MACD line's defined (non-NaN) region."""
    close = close.astype(float).reset_index(drop=True)
    macd_line = ema(close, fast) - ema(close, slow)
    defined = macd_line.dropna()
    signal_line = pd.Series(np.nan, index=close.index, dtype=float)
    if not defined.empty:
        sig_on_defined = ema(defined.reset_index(drop=True), signal)
        signal_line.loc[defined.index] = sig_on_defined.values
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger(close: pd.Series, period: int = 20, k: float = 2.0):
    """Returns (middle, upper, lower, percent_b, bandwidth). Population stddev (ddof=0)
    per §7.1 — REQUIRED to match TA references. sigma==0 -> %B=0.5, bandwidth=0."""
    close = close.astype(float).reset_index(drop=True)
    mid = close.rolling(period).mean()
    sigma = close.rolling(period).std(ddof=0)
    upper = mid + k * sigma
    lower = mid - k * sigma
    width = upper - lower
    percent_b = ((close - lower) / width).where(sigma != 0, 0.5)
    bandwidth = (width / mid).where(sigma != 0, 0.0)
    return mid, upper, lower, percent_b, bandwidth


def vol_z20(volume: pd.Series, period: int = 20) -> pd.Series:
    """20-bar volume z-score, population stddev, clipped to [-3, +6] (model contract,
    prediction-model.md §4.2). sigma==0 -> 0.0 (flat/halted)."""
    volume = volume.astype(float).reset_index(drop=True)
    mean = volume.rolling(period).mean()
    sigma = volume.rolling(period).std(ddof=0)
    z = ((volume - mean) / sigma).where(sigma != 0, 0.0)
    return z.clip(lower=-3.0, upper=6.0)


def crossover(fast: pd.Series, slow: pd.Series, cap: int = 20):
    """Most recent cross of `fast` over/under `slow` at or before the last bar.
    Returns (cross_dir, bars_since_cross): cross_dir in {+1 up, -1 down, 0 none},
    bars_since capped at `cap` (also the no-cross sentinel). §5.3 / §13."""
    f = fast.astype(float).reset_index(drop=True)
    s = slow.astype(float).reset_index(drop=True)
    sign = np.sign(f - s)
    diff = sign.diff()                       # +2 up-cross, -2 down-cross
    crosses = diff[(diff == 2) | (diff == -2)]
    if crosses.empty:
        return 0, cap
    last = crosses.index[-1]
    direction = 1 if diff.iloc[last] > 0 else -1
    bars_since = min(len(f) - 1 - last, cap)
    return direction, int(bars_since)


# --- Signal-state machines -------------------------------------------------

def rsi_state(rsi: float) -> str:
    if rsi >= 70:
        return "overbought"
    if rsi >= 60:
        return "bullish"
    if rsi >= 40:
        return "neutral"
    if rsi > 30:
        return "bearish"
    return "oversold"


def vol_state(z: float, *, first_bar_of_session: bool = False) -> str:
    surge_threshold = 3.0 if first_bar_of_session else 2.0   # §7A.3 session-open guard
    if z >= surge_threshold:
        return "surge"
    if z >= 1.0:
        return "elevated"
    if z > -1.0:
        return "normal"
    return "quiet"


def _rising(s: pd.Series, n: int = 3) -> bool:
    """True if the last n steps are strictly increasing."""
    tail = s.dropna().iloc[-(n + 1):]
    return len(tail) == n + 1 and bool((tail.diff().dropna() > 0).all())


def _shrinking_abs(s: pd.Series, n: int = 3) -> bool:
    """True if |s| strictly shrinks over the last n steps."""
    tail = s.dropna().abs().iloc[-(n + 1):]
    return len(tail) == n + 1 and bool((tail.diff().dropna() < 0).all())


def macd_state(*, cross_dir: int, bars_since_cross: int,
               zero_cross_dir: int, bars_since_zero_cross: int,
               hist: pd.Series) -> str:
    """Priority: signal-line cross > zero cross > histogram momentum. §6.3."""
    if cross_dir != 0 and bars_since_cross <= 3:
        return "bullish_cross" if cross_dir > 0 else "bearish_cross"
    if zero_cross_dir != 0 and bars_since_zero_cross <= 3:
        return "zero_cross_up" if zero_cross_dir > 0 else "zero_cross_down"
    last = hist.dropna()
    if len(last) and last.iloc[-1] > 0 and _rising(last):
        return "momentum_building"
    if _shrinking_abs(last):
        return "momentum_fading"
    return "neutral"


def bollinger_state(percent_b: pd.Series, bandwidth: pd.Series) -> str:
    """§7.3 (squeeze handled separately by bollinger_squeeze)."""
    b = percent_b.dropna()
    if b.empty:
        return "inside"
    cur = b.iloc[-1]
    prev = b.iloc[-2] if len(b) >= 2 else cur
    if cur > 1.0 and 0.0 <= prev <= 1.0:
        return "breakout_up"
    if cur < 0.0 and 0.0 <= prev <= 1.0:
        return "breakout_down"
    last3 = b.iloc[-3:]
    if len(last3) == 3 and bool((last3 >= 0.95).all()):
        return "riding_upper"
    if len(last3) == 3 and bool((last3 <= 0.05).all()):
        return "riding_lower"
    return "inside"


def bollinger_squeeze(bandwidth: pd.Series, window: int = 120, min_bars: int = 140):
    """True if current bandwidth is the lowest in the trailing `window` bars. None if
    fewer than `min_bars` of RAW history (§7.3: 140 = 120-bar window + 20-bar SMA seed).
    `bandwidth` carries one entry per raw bar (NaN for the first 19), so the floor gates
    on len(bandwidth) — NOT on the dropna count, which would demand 19 extra bars."""
    if len(bandwidth) < min_bars:
        return None
    bw = bandwidth.dropna()
    if bw.empty:
        return None
    trailing = bw.iloc[-window:]
    return bool(bw.iloc[-1] <= trailing.min())


def ema_stack(ema5: float, ema20: float, ema50: float, ema200: float):
    """Returns (bullish, bearish) booleans for the fully-ordered stack. §5.3."""
    vals = [ema5, ema20, ema50, ema200]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
        return (False, False)
    bullish = ema5 > ema20 > ema50 > ema200
    bearish = ema5 < ema20 < ema50 < ema200
    return (bool(bullish), bool(bearish))


# --- Capstone payload assembler -------------------------------------------

def _scalar(series_or_val):
    """Last value of a Series as a plain float, or None if NaN/empty/None."""
    if series_or_val is None:
        return None
    if isinstance(series_or_val, pd.Series):
        s = series_or_val.dropna()
        if s.empty:
            return None
        v = float(s.iloc[-1])
    else:
        v = float(series_or_val)
    return None if (v != v) else v   # NaN guard


def compute_indicators(bars: pd.DataFrame, *, bar_interval: str,
                       first_bar_of_session: bool = False) -> dict:
    """Assemble the technical-indicators.md §10.1 payload from an OHLCV frame.
    `bars` must have columns open/high/low/close/volume; bar t = last row."""
    close = bars["close"].astype(float).reset_index(drop=True)
    volume = bars["volume"].astype(float).reset_index(drop=True)
    n = len(close)
    c_t = float(close.iloc[-1])
    flags: list[str] = []

    # RSI
    rsi_series = rsi_wilder(close)
    rsi_val = _scalar(rsi_series)

    # EMAs
    ema5 = ema(close, 5); ema20 = ema(close, 20)
    ema50 = ema(close, 50); ema200 = ema(close, 200)
    ema5_v, ema20_v = _scalar(ema5), _scalar(ema20)
    ema50_v = _scalar(ema50)
    ema200_available = n >= 200
    ema200_v = _scalar(ema200) if ema200_available else None
    warming_up = ema200_available and n < 600   # 3 * 200 (§2 convergence)
    if warming_up:
        flags.append("warming_up")

    cd_5_20, bs_5_20 = crossover(ema5, ema20)
    cd_50_200, bs_50_200 = crossover(ema50, ema200) if ema200_available else (0, 20)
    stack_bull, stack_bear = ema_stack(
        ema5_v, ema20_v, ema50_v,
        ema200_v if ema200_v is not None else float("nan"))

    def _vs(ref):
        return (c_t - ref) / ref * 100 if ref else None   # full precision per §2

    # MACD
    macd_line, macd_signal_s, macd_hist = macd(close)
    macd_line_v = _scalar(macd_line)
    macd_signal_v = _scalar(macd_signal_s)
    macd_hist_v = _scalar(macd_hist)
    hist_clean = macd_hist.dropna()
    macd_hist_delta = (float(hist_clean.iloc[-1] - hist_clean.iloc[-2])
                       if len(hist_clean) >= 2 else None)
    macd_cross_dir, bars_since_macd_cross = crossover(macd_line, macd_signal_s)
    zero = pd.Series(0.0, index=macd_line.index)
    zc_dir, bs_zc = crossover(macd_line, zero)
    macd_st = macd_state(cross_dir=macd_cross_dir, bars_since_cross=bars_since_macd_cross,
                         zero_cross_dir=zc_dir, bars_since_zero_cross=bs_zc, hist=macd_hist)
    macd_line_pct = macd_line_v / c_t * 100 if macd_line_v is not None else None

    # Bollinger
    bb_mid, bb_up, bb_low, bb_pctb, bb_bw = bollinger(close)
    bb_state_v = bollinger_state(bb_pctb, bb_bw)
    bb_squeeze_v = bollinger_squeeze(bb_bw)
    bb_squeeze_prev = bollinger_squeeze(bb_bw.iloc[:-1])   # squeeze on the prior bar
    if bb_state_v == "breakout_up" and (bb_squeeze_v or bb_squeeze_prev):
        bb_state_v = "squeeze_breakout_up"   # breakout ending a squeeze — §7.3/§7.4 headline
    elif bb_squeeze_v and bb_state_v == "inside":
        bb_state_v = "squeeze"

    # Volume
    if n < 20:
        flags.append("insufficient_history")
        vol_z_v = None
        vol_st = None
    else:
        vol_z_v = _scalar(vol_z20(volume))
        vol_st = (vol_state(vol_z_v, first_bar_of_session=first_bar_of_session)
                  if vol_z_v is not None else None)
        # stale_price: 20 identical volumes (VolStd=0), even if prices still move (§7A.1)
        if float(volume.tail(20).std(ddof=0)) == 0 and "stale_price" not in flags:
            flags.append("stale_price")

    # stale_price: flat closes (RSI pinned to 50 by the flat-series rule)
    if (n >= 15 and rsi_val == 50.0 and close.tail(15).nunique() == 1
            and "stale_price" not in flags):
        flags.append("stale_price")
    # limit_lock: >=5 consecutive bars with high == low (KRX limit lock, §9.4)
    if n >= 5:
        hl_equal = (bars["high"].astype(float).reset_index(drop=True)
                    == bars["low"].astype(float).reset_index(drop=True))
        if bool(hl_equal.tail(5).all()):
            flags.append("limit_lock")

    # Stored at full float precision per §2; display rounding is the UI/copy layer's job.
    return {
        "rsi_14": rsi_val,
        "rsi_state": rsi_state(rsi_val) if rsi_val is not None else None,
        "ema_5": ema5_v, "ema_20": ema20_v,
        "ema_50": ema50_v, "ema_200": ema200_v,
        "ema_200_available": bool(ema200_available), "warming_up": bool(warming_up),
        "ema_5_20_cross_dir": cd_5_20, "bars_since_ema_5_20_cross": bs_5_20,
        "ema_50_200_cross_dir": cd_50_200, "bars_since_ema_50_200_cross": bs_50_200,
        "price_vs_ema20_pct": _vs(ema20_v), "price_vs_ema50_pct": _vs(ema50_v),
        "price_vs_ema200_pct": _vs(ema200_v),
        "ema_stack_bullish": stack_bull, "ema_stack_bearish": stack_bear,
        "macd_line": macd_line_v, "macd_signal": macd_signal_v,
        "macd_histogram": macd_hist_v, "macd_hist_delta": macd_hist_delta,
        "macd_line_pct": macd_line_pct, "macd_state": macd_st,
        "bars_since_macd_cross": bars_since_macd_cross,
        "bb_middle": _scalar(bb_mid), "bb_upper": _scalar(bb_up),
        "bb_lower": _scalar(bb_low), "bb_percent_b": _scalar(bb_pctb),
        "bb_bandwidth": _scalar(bb_bw), "bb_state": bb_state_v,
        "bb_squeeze": bb_squeeze_v,
        "vol_z20": vol_z_v, "vol_state": vol_st,
        "flags": flags,
    }
