"""Load M5 tunables from config/ml.yaml (prediction-model.md §10). DEAD_BAND_PCT is sourced
from app.tracking.labels (the grading contract), not duplicated here."""
import functools
from pathlib import Path

import yaml

from app.tracking.labels import DEAD_BAND_PCT  # re-export the canonical bands

TIMEFRAMES = ("1h", "5h", "24h", "2d", "3d", "5d")
_PATH = Path(__file__).resolve().parents[3] / "config" / "ml.yaml"

# Feature vector order (prediction-model.md §4.2) — the cross-doc CONTRACT.
FEATURE_NAMES = [
    "rsi_14", "rsi_slope_3", "ema_cross_state", "ema_bars_since_cross",
    "macd_hist_norm", "macd_hist_delta", "bb_position", "vol_z20",
    "sent_agg", "sent_delta_2h", "econ_high_impact_6h", "econ_impact_score",
    "xmkt_ref_return", "xmkt_corr_60d", "market_is_krx",
]
FEATURE_GROUP = {
    "rsi_14": "rsi", "rsi_slope_3": "rsi",
    "ema_cross_state": "ema", "ema_bars_since_cross": "ema",
    "macd_hist_norm": "macd", "macd_hist_delta": "macd",
    "bb_position": "bollinger", "vol_z20": "volume",
    "sent_agg": "sentiment", "sent_delta_2h": "sentiment",
    "econ_high_impact_6h": "econ_event", "econ_impact_score": "econ_event",
    "xmkt_ref_return": "cross_market", "xmkt_corr_60d": "cross_market",
    "market_is_krx": None,   # auxiliary — never shown in evidence
}


@functools.lru_cache
def load_ml_config() -> dict:
    cfg = yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}
    cfg["dead_band_pct"] = dict(DEAD_BAND_PCT)
    return cfg
