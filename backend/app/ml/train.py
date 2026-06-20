"""Per-timeframe model training (prediction-model.md §7). CLI:
    python -m app.ml.train --timeframe 2d [--db PATH] [--models-root DIR]

Pipeline: build_dataset -> chronological 70/15/15 split -> fit LR (C grid) + XGB (depth/mcw grid),
selecting each by VALIDATION directional win rate -> per-class calibration on validation -> evaluate
both on the untouched TEST slice -> ship the higher test win rate (LR on a <=0.5pp tie) -> 4-fold
walk-forward soft-warn -> write versioned artifact (model.pkl, scaler.pkl for LR, calibrators.pkl,
manifest.json) + feature_importance_logs rows.

ML libs are lazy-imported so importing this module never requires [ml]. Determinism: fixed
random_state and single-threaded fits, so re-running the same data reproduces the same artifact.

v1 notes (documented deferrals): tau_dir is taken from config (not re-tuned per fold); XGB uses a
fixed n_estimators (no early stopping); global feature importance uses XGB gain (per-prediction SHAP
is used at serve time, explain.py); the model is fit on train only (no refit on train+val)."""
import argparse
import asyncio
import json
import math
from pathlib import Path

from app.ml.calibrate import apply_calibration, ece, fit_calibrators
from app.ml.config import FEATURE_NAMES, load_ml_config
from app.ml.dataset import build_dataset
from app.ml.gate import apply_neutral_rule, directional_metrics, passes_gate
from app.ml.split import chronological_split, walk_forward_folds
from app.tracking.labels import DEAD_BAND_PCT

CLASS_ORDER = ["up", "down", "neutral"]
LR_C_GRID = [0.01, 0.1, 1.0, 10.0]
XGB_DEPTH_GRID = [3, 4, 5]
XGB_MCW_GRID = [5, 20]
XGB_N_ESTIMATORS = 300
FOLD_WARN_WIN = 0.48
MIN_SAMPLES = 20
_MODELS_ROOT = Path(__file__).resolve().parents[2] / "models"


# --- matrices -------------------------------------------------------------

def _impute_means(rows, train_idx, names):
    means = {}
    for f in names:
        vals = [rows[i]["features"][f] for i in train_idx if rows[i]["features"][f] is not None]
        means[f] = (sum(vals) / len(vals)) if vals else 0.0
    return means


def _matrix_lr(rows, names, means):
    return [[(r["features"][f] if r["features"][f] is not None else means[f]) for f in names]
            for r in rows]


def _matrix_xgb(rows, names):
    nan = float("nan")
    return [[(r["features"][f] if r["features"][f] is not None else nan) for f in names]
            for r in rows]


def _lr_probs(proba_row, classes):
    d = {c: 0.0 for c in CLASS_ORDER}
    for k, c in enumerate(classes):
        d[c] = float(proba_row[k])
    return d


def _xgb_probs(proba_row, classes_int):
    d = {c: 0.0 for c in CLASS_ORDER}
    for k, ci in enumerate(classes_int):
        d[CLASS_ORDER[int(ci)]] = float(proba_row[k])
    return d


def _metrics_rows(raw_by_idx, calibrators, idx, y, tau, *, calibrate=True):
    rows = []
    for i in idx:
        probs = apply_calibration(raw_by_idx[i], calibrators) if calibrate else raw_by_idx[i]
        disp, _ = apply_neutral_rule(probs, tau)
        rows.append((disp, y[i]))
    return directional_metrics(rows)


# --- per-algorithm training ----------------------------------------------

def _train_lr(Xs, y, train_idx, val_idx, tau):
    from sklearn.linear_model import LogisticRegression
    best = None
    for C in LR_C_GRID:
        clf = LogisticRegression(C=C, class_weight="balanced", max_iter=2000, random_state=0)
        clf.fit([Xs[i] for i in train_idx], [y[i] for i in train_idx])
        classes = list(clf.classes_)
        raw = {i: _lr_probs(clf.predict_proba([Xs[i]])[0], classes) for i in (*val_idx,)}
        cals = fit_calibrators([raw[i] for i in val_idx], [y[i] for i in val_idx],
                               n_val=len(val_idx))
        wr = _metrics_rows(raw, cals, val_idx, y, tau)["win_rate"]
        if best is None or wr > best["val_wr"]:
            best = {"C": C, "clf": clf, "classes": classes, "cals": cals, "val_wr": wr}
    return best


def _train_xgb(Xx, y, train_idx, val_idx, tau):
    import numpy as np
    from xgboost import XGBClassifier
    yi = [CLASS_ORDER.index(v) for v in y]
    Xtr = np.array([Xx[i] for i in train_idx], dtype=float)
    best = None
    for depth in XGB_DEPTH_GRID:
        for mcw in XGB_MCW_GRID:
            clf = XGBClassifier(max_depth=depth, min_child_weight=mcw, learning_rate=0.05,
                                n_estimators=XGB_N_ESTIMATORS, subsample=0.8, colsample_bytree=0.8,
                                reg_lambda=1.0, random_state=0, n_jobs=1, importance_type="gain",
                                eval_metric="mlogloss")
            clf.fit(Xtr, [yi[i] for i in train_idx])
            cls = clf.classes_
            raw = {i: _xgb_probs(clf.predict_proba(np.array([Xx[i]], dtype=float))[0], cls)
                   for i in val_idx}
            cals = fit_calibrators([raw[i] for i in val_idx], [y[i] for i in val_idx],
                                   n_val=len(val_idx))
            wr = _metrics_rows(raw, cals, val_idx, y, tau)["win_rate"]
            if best is None or wr > best["val_wr"]:
                best = {"params": {"max_depth": depth, "min_child_weight": mcw}, "clf": clf,
                        "classes": cls, "cals": cals, "val_wr": wr}
    return best


def _fold_winrate(algo, sel, Xs, Xx, y, train_idx, test_idx, tau):
    """Robustness refit per fold (raw probs + neutral rule; global preprocessing reused)."""
    import numpy as np
    if algo == "logistic":
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(C=sel["C"], class_weight="balanced", max_iter=2000, random_state=0)
        clf.fit([Xs[i] for i in train_idx], [y[i] for i in train_idx])
        classes = list(clf.classes_)
        raw = {i: _lr_probs(clf.predict_proba([Xs[i]])[0], classes) for i in test_idx}
    else:
        from xgboost import XGBClassifier
        clf = XGBClassifier(**sel["params"], learning_rate=0.05, n_estimators=XGB_N_ESTIMATORS,
                            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, random_state=0,
                            n_jobs=1, importance_type="gain", eval_metric="mlogloss")
        clf.fit(np.array([Xx[i] for i in train_idx], dtype=float),
                [CLASS_ORDER.index(y[i]) for i in train_idx])
        raw = {i: _xgb_probs(clf.predict_proba(np.array([Xx[i]], dtype=float))[0], clf.classes_)
               for i in test_idx}
    return _metrics_rows(raw, None, test_idx, y, tau, calibrate=False)["win_rate"]


def _feature_importance(algo, sel, scaler):
    if algo == "logistic":
        coef = sel["clf"].coef_                       # (n_classes, n_features) on standardized X
        return [(f"model_coef:{f}", float(sum(abs(coef[k][j]) for k in range(len(coef))) / len(coef)))
                for j, f in enumerate(FEATURE_NAMES)]
    imp = sel["clf"].feature_importances_             # XGB gain
    return [(f"model_gain:{f}", float(imp[j])) for j, f in enumerate(FEATURE_NAMES)]


# --- orchestrator ---------------------------------------------------------

def train_timeframe(samples, timeframe, cfg, *, now_iso, git_commit="unknown", seq=1):
    import numpy as np  # noqa: F401  (ensures [ml] present; matrices below need it for XGB)
    from sklearn.preprocessing import StandardScaler

    if len(samples) < MIN_SAMPLES:
        raise ValueError(f"only {len(samples)} samples for {timeframe}; need >= {MIN_SAMPLES}")
    samples = sorted(samples, key=lambda s: s["entry_ts"])
    y = [s["label"] for s in samples]
    tau = cfg["tau_dir"][timeframe]
    band = DEAD_BAND_PCT[timeframe]
    gate_cfg = cfg["ship_gate"]
    cap = cfg["staleness_confidence_cap"]   # noqa: F841 (recorded in manifest; applied at serve time)

    train_idx, val_idx, test_idx = chronological_split(len(samples))
    means = _impute_means(samples, train_idx, FEATURE_NAMES)
    X_lr = _matrix_lr(samples, FEATURE_NAMES, means)
    X_xgb = _matrix_xgb(samples, FEATURE_NAMES)
    scaler = StandardScaler().fit([X_lr[i] for i in train_idx])
    Xs = [list(row) for row in scaler.transform(X_lr)]

    lr = _train_lr(Xs, y, train_idx, val_idx, tau)
    xgb = _train_xgb(X_xgb, y, train_idx, val_idx, tau)

    lr_raw = {i: _lr_probs(lr["clf"].predict_proba([Xs[i]])[0], lr["classes"]) for i in test_idx}
    xgb_raw = {i: _xgb_probs(xgb["clf"].predict_proba(
        __import__("numpy").array([X_xgb[i]], dtype=float))[0], xgb["classes"]) for i in test_idx}
    lr_test = _metrics_rows(lr_raw, lr["cals"], test_idx, y, tau)
    xgb_test = _metrics_rows(xgb_raw, xgb["cals"], test_idx, y, tau)

    if xgb_test["win_rate"] > lr_test["win_rate"] + 0.005:    # within 0.5pp -> prefer LR
        algo, sel, test_m, test_raw = "xgboost", xgb, xgb_test, xgb_raw
    else:
        algo, sel, test_m, test_raw = "logistic", lr, lr_test, lr_raw

    folds = [(_fold_winrate(algo, sel, Xs, X_xgb, y, tr, te, tau))
             for tr, te in walk_forward_folds(len(samples), k=4)]
    min_fold = min(folds) if folds else 0.0

    test_ece = ece([apply_calibration(test_raw[i], sel["cals"]) for i in test_idx],
                   [y[i] for i in test_idx])
    importance = _feature_importance(algo, sel, scaler)

    algo_short = "lr" if algo == "logistic" else "xgb"
    yyyymmdd = now_iso[:10].replace("-", "")
    model_version = f"{timeframe}-{algo_short}-{yyyymmdd}.{seq}"

    import sklearn
    import xgboost
    manifest = {
        "model_version": model_version, "timeframe": timeframe, "algorithm": algo,
        "created_at": now_iso, "git_commit": git_commit,
        "n_samples": len(samples),
        "train_window": {"from": samples[0]["entry_ts"], "to": samples[-1]["entry_ts"]},
        "split": {"train": len(train_idx), "val": len(val_idx), "test": len(test_idx)},
        "neutral_band_pct": band, "tau_dir": tau, "staleness_confidence_cap": cap,
        "calibration_method": sel["cals"]["_method"], "ece": test_ece,
        "gate": {"win_rate": test_m["win_rate"], "coverage": test_m["coverage"],
                 "passed": passes_gate(test_m, gate_cfg), "thresholds": gate_cfg},
        "candidates": {"logistic": lr_test["win_rate"], "xgboost": xgb_test["win_rate"]},
        "walk_forward": [{"fold": j, "win_rate": w} for j, w in enumerate(folds)],
        "min_fold_win_rate": min_fold, "fold_warn": bool(min_fold < FOLD_WARN_WIN),
        "lib_versions": {"sklearn": sklearn.__version__, "xgboost": xgboost.__version__,
                         "numpy": __import__("numpy").__version__},
        "features": [{"name": f, "mean": means[f],
                      "std": (float(scaler.scale_[j]) if algo == "logistic" else None)}
                     for j, f in enumerate(FEATURE_NAMES)],
    }
    return {
        "model_version": model_version, "timeframe": timeframe, "algorithm": algo,
        "model": sel["clf"], "scaler": scaler if algo == "logistic" else None,
        "calibrators": sel["cals"], "manifest": manifest, "feature_importance": importance,
    }


def write_artifact(models_root: str, art: dict) -> str:
    import joblib
    d = Path(models_root) / art["timeframe"] / art["model_version"]
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(art["model"], d / "model.pkl")
    if art["scaler"] is not None:
        joblib.dump(art["scaler"], d / "scaler.pkl")
    joblib.dump(art["calibrators"], d / "calibrators.pkl")
    (d / "manifest.json").write_text(json.dumps(art["manifest"], indent=2), encoding="utf-8")
    return str(d)


async def persist_feature_importance(con, art: dict) -> None:
    w = art["manifest"]["train_window"]
    for name, score in art["feature_importance"]:
        await con.execute(
            "INSERT INTO feature_importance_logs "
            "(model_version, timeframe, feature_name, importance_score, window_start, window_end) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(model_version, feature_name) DO UPDATE SET "
            "importance_score=excluded.importance_score",
            (art["model_version"], art["timeframe"], name, score, w["from"], w["to"]))
    await con.commit()


# --- CLI (used by M5c on real backfilled history) -------------------------

class _NullRedis:
    """Training is an offline batch with no Redis. get() returns None instantly so build_features
    never blocks on a connection (econ staleness is a serve-time concern, irrelevant to training)."""
    async def get(self, *_a, **_k):
        return None


async def _run(timeframe, db, models_root, now_iso, git_commit):
    from app.db.connection import connect
    from app.db.repositories import stocks as srepo
    cfg = load_ml_config()
    async with connect(db) as con:
        refs = [r for r in await srepo.list_active_all(con) if r.exchange != "INDEX"]
        samples = await build_dataset(con, _NullRedis(), refs, timeframe)
        if len(samples) < MIN_SAMPLES:
            print(f"{timeframe}: only {len(samples)} samples (< {MIN_SAMPLES}) -> DISABLED (gate skipped)")
            return
        art = train_timeframe(samples, timeframe, cfg, now_iso=now_iso, git_commit=git_commit)
        out = write_artifact(models_root, art)
        await persist_feature_importance(con, art)
    g = art["manifest"]["gate"]
    print(f"{timeframe}: {art['algorithm']} {art['model_version']} -> win {g['win_rate']:.3f} "
          f"cov {g['coverage']:.3f} gate={'PASS' if g['passed'] else 'FAIL'} -> {out}")


def main(argv=None):
    from datetime import datetime, timezone
    p = argparse.ArgumentParser(description="Train one per-timeframe prediction model.")
    p.add_argument("--timeframe", required=True, choices=list(DEAD_BAND_PCT))
    p.add_argument("--db", default="dcintel.db")
    p.add_argument("--models-root", default=str(_MODELS_ROOT))
    p.add_argument("--git-commit", default="unknown")
    a = p.parse_args(argv)
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    asyncio.run(_run(a.timeframe, a.db, a.models_root, now_iso, a.git_commit))


if __name__ == "__main__":
    main()
