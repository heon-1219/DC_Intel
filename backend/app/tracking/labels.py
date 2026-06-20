"""Shared label/dead-band contract (prediction-model.md §3, win-loss-tracking.md §4.1).
Imported by BOTH M5 training (passes DEAD_BAND_PCT[timeframe]) and the M7 outcome checker
(passes the prediction's snapshotted reasoning_json.neutral_band_pct). One implementation so a
re-tune of the bands can never disagree between training and grading."""

# Per-timeframe neutral dead-band (|move_pct| < band -> neutral). Sized so neutral ~25-40%.
DEAD_BAND_PCT = {"1h": 0.15, "5h": 0.30, "24h": 0.40, "2d": 0.50, "3d": 0.60, "5d": 0.75}

# Label-window length in BARS of the tf's feed interval (§3): the exit is this many trading bars
# after entry. Exact for the regular-session-hours (1h/5h) and N-trading-day (2d/3d/5d) windows
# because the backfilled snapshot sequence contains only trading bars (no weekend/holiday gaps).
# "24h" (same-time next trading day) is intentionally NOT here — its variable session length means
# the dataset resolves it by wall-clock (first snapshot at/after entry + 24h).
HORIZON_BARS = {"1h": 12, "5h": 20, "2d": 2, "3d": 3, "5d": 5}


def derive_direction(change_pct: float, band_pct: float) -> str:
    """3-class label: up if move > band, down if move < -band, else neutral (strict)."""
    if change_pct > band_pct:
        return "up"
    if change_pct < -band_pct:
        return "down"
    return "neutral"
