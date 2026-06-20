"""Probability calibration (prediction-model.md §5.2). Per-class one-vs-rest: isotonic regression
when the validation split has >= 5000 samples, else Platt (sigmoid) scaling — isotonic overfits on
small samples. The three calibrated probabilities are renormalized to sum to 1. ECE (10 equal-width
bins) on the test split is recorded in the manifest (warn, don't block, if > 0.07).

Fit on the VALIDATION split ONLY (never train, never test). sklearn is lazy-imported so importing
this module doesn't require [ml]; only fit_calibrators needs it (apply works on stored calibrators)."""
_CLASSES = ("up", "down", "neutral")
ISOTONIC_MIN_VAL = 5000
ECE_WARN = 0.07


def _xy(raw_probs, labels, cls):
    return [rp[cls] for rp in raw_probs], [1 if lab == cls else 0 for lab in labels]


def fit_calibrators(raw_probs: list[dict], labels: list[str], n_val: int | None = None) -> dict:
    """Returns {class: (kind, model), ..., "_method": "isotonic"|"platt"}. A class that is all-0/all-1
    in the val split is degenerate -> ('const', base_rate)."""
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    n = n_val if n_val is not None else len(raw_probs)
    method = "isotonic" if n >= ISOTONIC_MIN_VAL else "platt"
    cals: dict = {"_method": method}
    for cls in _CLASSES:
        x, y = _xy(raw_probs, labels, cls)
        if len(set(y)) < 2:                                  # only one class present -> constant
            cals[cls] = ("const", (sum(y) / len(y)) if y else 0.0)
        elif method == "isotonic":
            ir = IsotonicRegression(out_of_bounds="clip")
            ir.fit(x, y)
            cals[cls] = ("isotonic", ir)
        else:
            lr = LogisticRegression()
            lr.fit([[v] for v in x], y)
            cals[cls] = ("platt", lr)
    return cals


def _cal_one(model, p: float) -> float:
    kind, m = model
    if kind == "const":
        return float(m)
    if kind == "isotonic":
        return float(m.predict([p])[0])
    return float(m.predict_proba([[p]])[0][1])               # platt


def apply_calibration(raw: dict, calibrators: dict) -> dict:
    """Calibrate each class probability then renormalize to a valid distribution (sum 1)."""
    vals = {cls: _cal_one(calibrators[cls], raw[cls]) for cls in _CLASSES}
    s = sum(vals.values())
    if s <= 0:
        return {cls: 1 / 3 for cls in _CLASSES}              # degenerate -> uniform
    return {cls: v / s for cls, v in vals.items()}


def ece(raw_probs: list[dict], labels: list[str], bins: int = 10) -> float:
    """Expected Calibration Error over the predicted (argmax) class: bin by confidence into `bins`
    equal-width buckets (lo, hi], weight |accuracy - mean_confidence| by bucket share."""
    preds = [(max(rp, key=rp.get), max(rp.values())) for rp in raw_probs]
    n = len(preds)
    if n == 0:
        return 0.0
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, (_, conf) in enumerate(preds) if lo < conf <= hi]
        if not idx:
            continue
        conf_mean = sum(preds[i][1] for i in idx) / len(idx)
        acc = sum(1 for i in idx if preds[i][0] == labels[i]) / len(idx)
        total += abs(acc - conf_mean) * len(idx) / n
    return total
