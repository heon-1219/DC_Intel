"""M6e gate-aware artifact loader (prediction-model SERVING §1 + disabled-with-note). Only
timeframes whose latest promoted manifest has gate.passed==true are servable."""
import json
from pathlib import Path

import joblib
import pytest

from app.ml.serving import loader


def _write(root, tf, version, passed, algo="logistic", created_at="2026-06-20T00:00:00Z"):
    d = Path(root) / tf / version
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({
        "model_version": version, "algorithm": algo, "created_at": created_at,
        "gate": {"passed": passed}}), encoding="utf-8")
    joblib.dump({"kind": "model"}, d / "model.pkl")
    joblib.dump({"kind": "cal"}, d / "calibrators.pkl")
    if algo == "logistic":
        joblib.dump({"kind": "scaler"}, d / "scaler.pkl")
    return d


@pytest.fixture(autouse=True)
def _clear():
    loader.clear_cache()
    yield
    loader.clear_cache()


def test_list_servable_only_gate_passed(tmp_path):
    _write(tmp_path, "5d", "5d-lr-20260620.1", passed=True)
    _write(tmp_path, "1h", "1h-lr-20260620.1", passed=False)
    assert loader.list_servable_timeframes(str(tmp_path)) == ["5d"]


def test_resolve_promoted_picks_latest_created(tmp_path):
    _write(tmp_path, "5d", "5d-lr-20260618.1", passed=True, created_at="2026-06-18T00:00:00Z")
    newer = _write(tmp_path, "5d", "5d-lr-20260620.1", passed=True, created_at="2026-06-20T00:00:00Z")
    assert loader.resolve_promoted(str(tmp_path), "5d") == newer


def test_resolve_promoted_none_when_all_failed(tmp_path):
    _write(tmp_path, "2d", "2d-lr-20260620.1", passed=False)
    assert loader.resolve_promoted(str(tmp_path), "2d") is None
    assert loader.resolve_promoted(str(tmp_path), "missing") is None   # no dir, no crash


def test_load_artifact_scaler_presence_by_algo(tmp_path):
    _write(tmp_path, "5d", "5d-lr-20260620.1", passed=True, algo="logistic")
    _write(tmp_path, "3d", "3d-xgb-20260620.1", passed=True, algo="xgboost")
    lr = loader.load_artifact(str(tmp_path), "5d")
    xgb = loader.load_artifact(str(tmp_path), "3d")
    assert lr.scaler is not None and lr.manifest["algorithm"] == "logistic"
    assert xgb.scaler is None and xgb.manifest["algorithm"] == "xgboost"


def test_load_artifact_is_cached(tmp_path, monkeypatch):
    _write(tmp_path, "5d", "5d-lr-20260620.1", passed=True)
    calls = {"n": 0}
    real = joblib.load
    monkeypatch.setattr(loader.joblib, "load", lambda p: (calls.__setitem__("n", calls["n"] + 1), real(p))[1])
    loader.load_artifact(str(tmp_path), "5d")
    after_first = calls["n"]
    loader.load_artifact(str(tmp_path), "5d")
    assert after_first == 3 and calls["n"] == after_first   # 2nd call hits cache (no extra loads)


def test_load_artifact_unavailable_raises(tmp_path):
    _write(tmp_path, "2d", "2d-lr-20260620.1", passed=False)
    with pytest.raises(loader.ModelUnavailable):
        loader.load_artifact(str(tmp_path), "2d")
