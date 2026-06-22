"""Loader robustness: a gate-passed manifest with NO weights (the migration case — tracked manifest,
gitignored .pkl) must NOT be servable (else /predict 500s on joblib.load instead of a clean 503)."""
import json
from pathlib import Path

from app.ml.serving import loader


def _manifest(d: Path, passed: bool) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(
        json.dumps({"model_version": d.name, "created_at": "2026-06-20T00:00:00Z",
                    "gate": {"passed": passed}}),
        encoding="utf-8")


def test_passed_manifest_without_weights_is_not_servable(tmp_path):
    root = tmp_path / "models"
    _manifest(root / "5d" / "5d-lr-noweights", True)  # gate passed but no model.pkl
    assert loader.resolve_promoted(str(root), "5d") is None
    assert "5d" not in loader.list_servable_timeframes(str(root))


def test_passed_manifest_with_weights_is_servable(tmp_path):
    root = tmp_path / "models"
    d = root / "5d" / "5d-lr-weights"
    _manifest(d, True)
    (d / "model.pkl").write_text("x", encoding="utf-8")
    (d / "calibrators.pkl").write_text("x", encoding="utf-8")
    assert loader.resolve_promoted(str(root), "5d") == d
    assert "5d" in loader.list_servable_timeframes(str(root))
