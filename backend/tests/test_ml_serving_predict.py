"""M6f serve-time inference -> reasoning_json (prediction-model SERVING §3-8, §8.1).
Builds a deterministic LR artifact in-memory and asserts the assembled reasoning_json + invariants."""
from types import SimpleNamespace

import pytest

pytest.importorskip("sklearn")

from sklearn.linear_model import LogisticRegression          # noqa: E402
from sklearn.preprocessing import StandardScaler             # noqa: E402

from app.ml.calibrate import fit_calibrators                 # noqa: E402
from app.ml.config import FEATURE_NAMES                      # noqa: E402
from app.ml.serving.loader import Artifact                   # noqa: E402
from app.ml.serving.predict import compute_window_close, run_inference   # noqa: E402

_REF = SimpleNamespace(symbol="005930", exchange="KRX", currency="KRW")


def _lr_artifact():
    X, y = [], []
    for i in range(150):
        r = (i * 13) % 100
        y.append("up" if r >= 60 else ("down" if r < 40 else "neutral"))
        row = [0.0] * 15
        row[0] = float(r)          # rsi_14 drives the label
        X.append(row)
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)
    clf = LogisticRegression(max_iter=2000, random_state=0).fit(Xs, y)
    raw = [{c: float(p) for c, p in zip(clf.classes_, clf.predict_proba([Xs[i]])[0])}
           for i in range(len(X))]
    cals = fit_calibrators(raw, y, n_val=len(X))
    manifest = {
        "model_version": "5d-lr-20260620.1", "algorithm": "logistic", "tau_dir": 0.45,
        "staleness_confidence_cap": 65, "neutral_band_pct": 0.5,
        "features": [{"name": n, "mean": float(scaler.mean_[i]), "std": float(scaler.scale_[i])}
                     for i, n in enumerate(FEATURE_NAMES)],
    }
    return Artifact(model=clf, scaler=scaler, calibrators=cals, manifest=manifest)


def _meta(missing=None, stale=None, any_stale=False, events=None):
    miss = {n: False for n in FEATURE_NAMES}
    if missing:
        miss.update({k: True for k in missing})
    st = {n: False for n in FEATURE_NAMES}
    if stale:
        st.update({k: True for k in stale})
    return {"missing": miss, "stale": st, "any_stale": any_stale,
            "high_impact_events": events or []}


def _vec(**kw):
    v = {n: 0.0 for n in FEATURE_NAMES}
    v.update(kw)
    return v


def test_reasoning_json_shape_and_invariants():
    art = _lr_artifact()
    rj = run_inference(art, _vec(rsi_14=85.0), _meta(), stock_ref=_REF, timeframe="5d",
                       as_of="2026-06-19T00:00:00Z", entry_price=84300.0,
                       window_closes_at="2026-06-26T00:00:00Z")
    assert rj["schema_version"] == 1
    assert rj["model_version"] == "5d-lr-20260620.1" and rj["algorithm"] == "logistic"
    assert rj["symbol"] == "005930:KRX" and rj["timeframe"] == "5d"
    assert rj["entry_price"] == 84300.0 and rj["neutral_band_pct"] == 0.5
    assert rj["direction"] in ("up", "down", "neutral")
    assert 0 <= rj["confidence"] <= 100
    assert abs(sum(rj["probabilities"]["calibrated"].values()) - 1.0) < 1e-6
    assert abs(sum(rj["probabilities"]["raw"].values()) - 1.0) < 1e-6
    assert len(rj["features"]) == 15
    assert [f["name"] for f in rj["features"]] == FEATURE_NAMES
    if rj["evidence"]:
        assert sum(e["contribution_pct"] for e in rj["evidence"]) == 100
        assert all(e["group"] != "market_is_krx" for e in rj["evidence"])   # aux never in evidence
    assert set(rj["data_staleness"]) >= {"any_stale", "technicals_age_sec", "xmkt_age_sec"}
    assert rj["data_staleness"]["any_stale"] is False


def test_confidence_capped_when_stale():
    art = _lr_artifact()
    rj = run_inference(art, _vec(rsi_14=95.0), _meta(stale=["rsi_14"], any_stale=True),
                       stock_ref=_REF, timeframe="5d", as_of="2026-06-19T00:00:00Z",
                       entry_price=100.0, window_closes_at="2026-06-26T00:00:00Z")
    assert rj["confidence"] <= 65
    assert rj["confidence_capped"] is True
    assert rj["data_staleness"]["any_stale"] is True


def test_missing_feature_flagged_and_excluded_from_evidence():
    art = _lr_artifact()
    rj = run_inference(art, _vec(rsi_14=85.0, sent_agg=None), _meta(missing=["sent_agg"]),
                       stock_ref=_REF, timeframe="5d", as_of="2026-06-19T00:00:00Z",
                       entry_price=1.0, window_closes_at="2026-06-26T00:00:00Z")
    sent = next(f for f in rj["features"] if f["name"] == "sent_agg")
    assert sent["missing"] is True
    assert all(e["group"] != "sentiment" for e in rj["evidence"])   # missing group not in evidence


@pytest.mark.parametrize("tf,as_of,expected", [
    ("1h", "2026-06-19T05:00:00Z", "2026-06-19T06:00:00Z"),     # +1h
    ("5h", "2026-06-19T05:00:00Z", "2026-06-19T10:00:00Z"),     # +5h
    ("24h", "2026-06-19T05:00:00Z", "2026-06-22T05:00:00Z"),    # Fri +1d -> skip weekend -> Mon
    ("2d", "2026-06-19T05:00:00Z", "2026-06-23T05:00:00Z"),     # Fri +2 business days -> Tue
    ("5d", "2026-06-19T05:00:00Z", "2026-06-26T05:00:00Z"),     # Fri +5 business days -> next Fri
])
def test_compute_window_close_business_days(tf, as_of, expected):
    assert compute_window_close(as_of, tf) == expected
