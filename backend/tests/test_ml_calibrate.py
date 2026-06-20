"""M5b probability calibration (prediction-model.md §5.2). Per-class one-vs-rest isotonic
(>=5000 val samples) else Platt; renormalize the 3 calibrated probs to sum 1; ECE (10 bins) warn.
Fit on VALIDATION only. sklearn-guarded (skips if [ml] not installed)."""
import pytest

pytest.importorskip("sklearn")

from app.ml.calibrate import apply_calibration, ece, fit_calibrators   # noqa: E402


def _synth(n):
    """Deterministic synthetic val set: raw P(up) sweeps 0.05..0.95; label correlates with it."""
    rows, labels = [], []
    for i in range(n):
        up = (i % 10) / 10.0 + 0.05
        rows.append({"up": up, "down": (1 - up) * 0.6, "neutral": (1 - up) * 0.4})
        labels.append("up" if (i % 10) >= 5 else "down")
    return rows, labels


def test_method_is_platt_for_small_val():
    rows, labels = _synth(200)
    cals = fit_calibrators(rows, labels)
    assert cals["_method"] == "platt"        # < 5000 -> Platt (isotonic overfits small samples)


def test_method_is_isotonic_for_large_val():
    rows, labels = _synth(5000)
    cals = fit_calibrators(rows, labels)
    assert cals["_method"] == "isotonic"     # >= 5000 -> isotonic


def test_apply_calibration_is_valid_distribution():
    rows, labels = _synth(300)
    cals = fit_calibrators(rows, labels)
    out = apply_calibration({"up": 0.7, "down": 0.2, "neutral": 0.1}, cals)
    assert set(out) == {"up", "down", "neutral"}
    assert sum(out.values()) == pytest.approx(1.0)         # renormalized
    assert all(0.0 <= v <= 1.0 for v in out.values())


def test_ece_perfect_is_zero():
    rows = [{"up": 1.0, "down": 0.0, "neutral": 0.0}] * 20
    labels = ["up"] * 20
    assert ece(rows, labels) == pytest.approx(0.0)


def test_ece_overconfident_is_high():
    rows = [{"up": 0.95, "down": 0.03, "neutral": 0.02}] * 20
    labels = (["up"] * 10) + (["down"] * 10)               # only 50% correct at 95% confidence
    assert ece(rows, labels) > 0.07                        # would trip the manifest warning
