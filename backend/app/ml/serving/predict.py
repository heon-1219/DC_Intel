"""Serve-time inference -> reasoning_json (prediction-model SERVING §3-8, §8.1).

run_inference takes a loaded Artifact + the feature vector/meta from build_features and assembles the
full reasoning_json: vectorize (LR: impute manifest mean then scaler.transform; XGB: NaN) ->
predict_proba -> apply_calibration -> apply_neutral_rule -> confidence (staleness cap) ->
per-feature contributions toward the displayed class (LR coef x standardized; XGB SHAP best-effort)
-> build_evidence -> the §8.1 document. Pure inference (no DB/Redis) — the endpoint (M6h) supplies
entry_price, window_closes_at, and persistence.

v1 note: data_staleness reports any_stale (which drives the cap) + per-feature stale flags in
features[]; the aggregate *_age_sec fields are present but null (the builder surfaces booleans, not
ages — exact ages are a documented refinement)."""
from datetime import datetime, timedelta, timezone

from app.ml.config import FEATURE_GROUP, FEATURE_NAMES
from app.ml.calibrate import apply_calibration
from app.ml.explain import build_evidence, feature_contributions_lr
from app.ml.gate import apply_neutral_rule, confidence

CLASS_ORDER = ["up", "down", "neutral"]
_STALE_KEYS = ("prices", "technicals", "sentiment", "intel", "econ", "xmkt")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def compute_window_close(as_of: str, timeframe: str) -> str:
    """Serve-time window close (v1 business-day stepper; exact holiday calendar = refinement).
    1h/5h = +wall-clock hours; 24h = next trading day same time; 2d/3d/5d = +N business days."""
    dt = _parse(as_of)
    if timeframe in ("1h", "5h"):
        end = dt + timedelta(hours=int(timeframe[:-1]))
    elif timeframe == "24h":
        end = dt + timedelta(days=1)
        while end.weekday() >= 5:          # land on a weekday
            end += timedelta(days=1)
    else:
        n = {"2d": 2, "3d": 3, "5d": 5}[timeframe]
        end, added = dt, 0
        while added < n:
            end += timedelta(days=1)
            if end.weekday() < 5:
                added += 1
    return _iso(end)


def _probs(model, proba_row) -> dict:
    out = {"up": 0.0, "down": 0.0, "neutral": 0.0}
    for c, p in zip(list(model.classes_), proba_row):
        out[c if isinstance(c, str) else CLASS_ORDER[int(c)]] = float(p)
    return out


def _contribs_lr(model, x_std, displayed):
    classes = list(model.classes_)
    coef = model.coef_
    idx = classes.index(displayed) if displayed in classes else 0
    row = coef[idx] if coef.shape[0] > 1 else coef[0]   # binary edge: single row
    coef_row = {FEATURE_NAMES[i]: float(row[i]) for i in range(len(FEATURE_NAMES))}
    x_std_d = {FEATURE_NAMES[i]: float(x_std[i]) for i in range(len(FEATURE_NAMES))}
    return feature_contributions_lr(coef_row, x_std_d)


def _contribs_xgb(model, x_row, displayed):
    try:   # best-effort SHAP; XGB isn't shipped in v1 (only the LR 5d passes the gate)
        import numpy as np
        import shap
        sv = shap.TreeExplainer(model).shap_values(np.array([x_row], dtype=float))
        arr = sv[CLASS_ORDER.index(displayed)] if isinstance(sv, list) else sv
        vals = arr[0]
        return {FEATURE_NAMES[i]: float(vals[i]) for i in range(len(FEATURE_NAMES))}
    except Exception:  # noqa: BLE001
        return {}


def run_inference(artifact, vector: dict, meta: dict, *, stock_ref, timeframe: str, as_of: str,
                  entry_price, window_closes_at: str) -> dict:
    import numpy as np
    m = artifact.manifest
    mean_of = {f["name"]: f["mean"] for f in m["features"]}
    is_lr = m["algorithm"] == "logistic"

    # vectorize (FEATURE_NAMES order)
    imputed = [vector[n] if vector[n] is not None else mean_of.get(n, 0.0) for n in FEATURE_NAMES]
    if is_lr:
        x_std = artifact.scaler.transform([imputed])[0]
        raw = _probs(artifact.model, artifact.model.predict_proba([x_std])[0])
    else:
        x_row = [vector[n] if vector[n] is not None else float("nan") for n in FEATURE_NAMES]
        raw = _probs(artifact.model, artifact.model.predict_proba(np.array([x_row], dtype=float))[0])

    calibrated = apply_calibration(raw, artifact.calibrators)
    displayed, neutral_rule_applied = apply_neutral_rule(calibrated, m["tau_dir"])
    cap = m["staleness_confidence_cap"]
    raw_conf = round(100 * calibrated[displayed])
    conf = confidence(calibrated[displayed], any_stale=meta["any_stale"], cap=cap)

    if is_lr:
        contribs = _contribs_lr(artifact.model, x_std, displayed)
    else:
        contribs = _contribs_xgb(artifact.model, x_row, displayed)
    missing_set = {n for n in FEATURE_NAMES if meta["missing"][n]}
    evidence = build_evidence(contribs, FEATURE_GROUP, missing_set, displayed)

    features_block = [{
        "name": n, "group": FEATURE_GROUP[n],
        "value": (vector[n] if vector[n] is not None else mean_of.get(n)),
        "baseline": mean_of.get(n),
        "contribution_signed": round(contribs.get(n, 0.0), 6),
        "missing": meta["missing"][n], "stale": meta["stale"][n],
    } for n in FEATURE_NAMES]

    staleness = {f"{k}_age_sec": None for k in _STALE_KEYS}
    staleness["any_stale"] = meta["any_stale"]

    return {
        "schema_version": 1, "model_version": m["model_version"], "algorithm": m["algorithm"],
        "timeframe": timeframe, "symbol": f"{stock_ref.symbol}:{stock_ref.exchange}",
        "predicted_at": as_of, "window_closes_at": window_closes_at, "entry_price": entry_price,
        "neutral_band_pct": m["neutral_band_pct"], "direction": displayed, "confidence": conf,
        "probabilities": {"raw": {k: round(v, 4) for k, v in raw.items()},
                          "calibrated": {k: round(v, 4) for k, v in calibrated.items()}},
        "neutral_rule_applied": neutral_rule_applied, "confidence_capped": conf < raw_conf,
        "features": features_block, "evidence": evidence,
        "data_staleness": staleness, "high_impact_events": meta["high_impact_events"],
    }
