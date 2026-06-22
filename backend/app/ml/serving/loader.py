"""Gate-aware model artifact loader (prediction-model SERVING §1). Mirrors train.write_artifact's
on-disk layout: {model_dir}/{tf}/{model_version}/{model.pkl, scaler.pkl (LR only), calibrators.pkl,
manifest.json}. A timeframe is SERVABLE only if its latest-promoted manifest has gate.passed==true
(the disabled-with-note guard). joblib is imported at module load (it's already an [ml] dep used by
training); artifacts are process-cached by (timeframe, model_version)."""
import json
from dataclasses import dataclass
from pathlib import Path

import joblib

from app.ml.config import TIMEFRAMES


@dataclass(frozen=True)
class Artifact:
    model: object
    scaler: object | None      # None for XGBoost (no StandardScaler)
    calibrators: dict
    manifest: dict


class ModelUnavailable(Exception):
    """The timeframe has no gate-passed promoted artifact (disabled-with-note)."""


_CACHE: dict = {}


def clear_cache() -> None:
    _CACHE.clear()


def _versions(model_dir: str, timeframe: str):
    base = Path(model_dir) / timeframe
    if not base.is_dir():
        return []
    out = []
    for d in base.iterdir():
        mf = d / "manifest.json"
        if mf.is_file():
            try:
                out.append((d, json.loads(mf.read_text(encoding="utf-8"))))
            except (ValueError, OSError):
                continue
    return out


def _has_weights(d: Path) -> bool:
    """A promoted artifact must ship its weights, not just a manifest — guards the migration case
    where manifests are tracked but the .pkl are gitignored/absent (else /predict 500s on load)."""
    return (d / "model.pkl").is_file() and (d / "calibrators.pkl").is_file()


def resolve_promoted(model_dir: str, timeframe: str) -> Path | None:
    """The directory of the latest (by created_at) gate-PASSED artifact WITH weights present, or None."""
    passed = [(d, m) for d, m in _versions(model_dir, timeframe)
              if m.get("gate", {}).get("passed") and _has_weights(d)]
    if not passed:
        return None
    passed.sort(key=lambda dm: dm[1].get("created_at", ""), reverse=True)
    return passed[0][0]


def list_servable_timeframes(model_dir: str) -> list[str]:
    """Canonical-order list of timeframes with a gate-passed promoted artifact."""
    return [tf for tf in TIMEFRAMES if resolve_promoted(model_dir, tf) is not None]


def load_artifact(model_dir: str, timeframe: str) -> Artifact:
    d = resolve_promoted(model_dir, timeframe)
    if d is None:
        raise ModelUnavailable(timeframe)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    key = (timeframe, manifest["model_version"])
    if key not in _CACHE:
        scaler_p = d / "scaler.pkl"
        _CACHE[key] = Artifact(
            model=joblib.load(d / "model.pkl"),
            scaler=joblib.load(scaler_p) if scaler_p.is_file() else None,
            calibrators=joblib.load(d / "calibrators.pkl"),
            manifest=manifest,
        )
    return _CACHE[key]
