"""Shared label/dead-band contract (prediction-model.md §3, win-loss-tracking.md §4.1).
Imported by BOTH M5 training (passes DEAD_BAND_PCT[timeframe]) and the M7 outcome checker
(passes the prediction's snapshotted reasoning_json.neutral_band_pct). One implementation so a
re-tune of the bands can never disagree between training and grading."""

# Per-timeframe neutral dead-band (|move_pct| < band -> neutral). Sized so neutral ~25-40%.
DEAD_BAND_PCT = {"1h": 0.15, "5h": 0.30, "24h": 0.40, "2d": 0.50, "3d": 0.60, "5d": 0.75}


def derive_direction(change_pct: float, band_pct: float) -> str:
    """3-class label: up if move > band, down if move < -band, else neutral (strict)."""
    if change_pct > band_pct:
        return "up"
    if change_pct < -band_pct:
        return "down"
    return "neutral"
