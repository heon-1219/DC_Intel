"""M5b training orchestrator smoke (prediction-model.md §7). Trains LR+XGB on a tiny in-memory
fixture (plan: offline tests use fixtures; REAL training is M5c on backfilled yfinance history),
picks the winner, and writes versioned artifacts + manifest + feature-importance rows.
sklearn/xgboost-guarded."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("xgboost")

from app.db.connection import connect            # noqa: E402
from app.db.migrate import migrate               # noqa: E402
from app.ml.config import FEATURE_NAMES, load_ml_config   # noqa: E402
from app.ml.train import (persist_feature_importance, train_timeframe,   # noqa: E402
                          write_artifact)

MIG = str(Path(__file__).resolve().parents[1] / "migrations")


def _samples(n=150):
    """Clean, learnable 3-class signal: label is determined by rsi_14 so a fitted model is
    confident -> exercises the gate-pass path. All features present (no missing) for the smoke."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        r = (i * 13) % 100                       # 0..99, repeating distribution
        if r >= 60:
            lab, ema = "up", 1.0
        elif r < 40:
            lab, ema = "down", -1.0
        else:
            lab, ema = "neutral", 0.0
        feats = {name: 0.0 for name in FEATURE_NAMES}
        feats["rsi_14"] = float(r)
        feats["rsi_slope_3"] = (r - 50) / 10.0
        feats["ema_cross_state"] = ema
        feats["macd_hist_norm"] = (r - 50) / 1000.0
        feats["market_is_krx"] = 1.0
        ts = (base + timedelta(days=i)).isoformat().replace("+00:00", "Z")
        out.append({"entry_ts": ts, "label": lab, "features": feats, "move_pct": 0.0})
    return out


def test_train_timeframe_produces_artifact_and_manifest():
    art = train_timeframe(_samples(), "2d", load_ml_config(),
                          now_iso="2026-06-20T00:00:00Z", git_commit="abc1234")
    assert art["algorithm"] in ("logistic", "xgboost")
    assert art["model_version"].startswith("2d-") and "20260620" in art["model_version"]
    m = art["manifest"]
    assert m["neutral_band_pct"] == 0.50 and m["tau_dir"] == 0.45
    assert set(m["gate"]) >= {"win_rate", "coverage", "passed"}
    assert isinstance(m["gate"]["passed"], bool)
    assert len(m["features"]) == 15 and all("mean" in f for f in m["features"])
    assert "sklearn" in m["lib_versions"] and "xgboost" in m["lib_versions"]
    assert len(m["walk_forward"]) == 4
    assert len(art["feature_importance"]) == 15      # one row per feature
    assert art["feature_importance"][0][0].startswith(("model_coef:", "model_gain:"))


def test_clean_signal_passes_gate():
    art = train_timeframe(_samples(), "2d", load_ml_config(),
                          now_iso="2026-06-20T00:00:00Z", git_commit="abc1234")
    # a deterministic rsi->label signal should clear 52% win / 30% coverage
    assert art["manifest"]["gate"]["passed"] is True


def test_training_is_deterministic():
    cfg = load_ml_config()
    a1 = train_timeframe(_samples(), "2d", cfg, now_iso="2026-06-20T00:00:00Z", git_commit="x")
    a2 = train_timeframe(_samples(), "2d", cfg, now_iso="2026-06-20T00:00:00Z", git_commit="x")
    assert a1["algorithm"] == a2["algorithm"]
    assert a1["manifest"]["gate"]["win_rate"] == a2["manifest"]["gate"]["win_rate"]


def test_write_artifact_files_and_reload(tmp_path):
    import joblib
    art = train_timeframe(_samples(), "2d", load_ml_config(),
                          now_iso="2026-06-20T00:00:00Z", git_commit="abc1234")
    out = write_artifact(str(tmp_path), art)
    d = Path(out)
    assert (d / "model.pkl").exists()
    assert (d / "calibrators.pkl").exists()
    assert (d / "manifest.json").exists()
    assert (d / "scaler.pkl").exists() == (art["algorithm"] == "logistic")
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["model_version"] == art["model_version"]
    model = joblib.load(d / "model.pkl")            # round-trips to a usable estimator
    assert hasattr(model, "predict_proba")


@pytest.mark.asyncio
async def test_persist_feature_importance_rows(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    art = train_timeframe(_samples(), "2d", load_ml_config(),
                          now_iso="2026-06-20T00:00:00Z", git_commit="abc1234")
    async with connect(db) as con:
        await persist_feature_importance(con, art)
        cur = await con.execute(
            "SELECT COUNT(*) c FROM feature_importance_logs WHERE model_version=?",
            (art["model_version"],))
        assert (await cur.fetchone())["c"] == 15
