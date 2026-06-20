"""M5b ship-gate + neutral-rule + confidence math (prediction-model.md §5.3/§5.4/§7.6).
Pure functions, oracle-tested — no ML libs, no I/O."""
import pytest

from app.ml.gate import (apply_neutral_rule, confidence, directional_metrics,
                         passes_gate, promotion_ok)


@pytest.mark.parametrize("probs,expected", [
    ({"up": 0.64, "down": 0.17, "neutral": 0.19}, ("up", False)),       # strong up
    ({"up": 0.50, "down": 0.30, "neutral": 0.20}, ("up", False)),       # up at/above tau
    ({"up": 0.41, "down": 0.38, "neutral": 0.21}, ("neutral", True)),   # downgrade: 0.41 < 0.45
    ({"up": 0.20, "down": 0.44, "neutral": 0.36}, ("neutral", True)),   # down downgraded
    ({"up": 0.30, "down": 0.20, "neutral": 0.50}, ("neutral", False)),  # argmax-neutral, not a rule
])
def test_apply_neutral_rule(probs, expected):
    assert apply_neutral_rule(probs, tau_dir=0.45) == expected


def test_apply_neutral_rule_exactly_at_tau_is_directional():
    # max(p_up,p_down) == tau is NOT below tau -> stays directional (strict <).
    assert apply_neutral_rule({"up": 0.45, "down": 0.30, "neutral": 0.25}, 0.45) == ("up", False)


def test_confidence_basic_and_cap():
    assert confidence(0.66, any_stale=False) == 66
    assert confidence(0.214, any_stale=False) == 21        # honest low-confidence neutral
    assert confidence(0.90, any_stale=True) == 65          # staleness cap
    assert confidence(0.50, any_stale=True) == 50          # below cap -> unchanged


def test_directional_metrics_neutral_realized_is_loss():
    rows = [("up", "up"), ("up", "down"), ("down", "down"),
            ("neutral", "up"), ("up", "neutral")]
    m = directional_metrics(rows)
    assert m["n_total"] == 5
    assert m["n_directional"] == 4          # the 3 'up' + 1 'down'
    assert m["wins"] == 2                   # (up,up) and (down,down); (up,neutral) is a LOSS
    assert m["win_rate"] == pytest.approx(0.5)
    assert m["coverage"] == pytest.approx(0.8)


def test_directional_metrics_all_neutral():
    m = directional_metrics([("neutral", "up"), ("neutral", "neutral")])
    assert m["n_directional"] == 0
    assert m["win_rate"] == 0.0 and m["coverage"] == 0.0   # no directional calls


@pytest.mark.parametrize("win,cov,ok", [
    (0.52, 0.30, True),    # exactly at both thresholds -> pass (>=)
    (0.60, 0.45, True),
    (0.51, 0.40, False),   # win too low
    (0.70, 0.29, False),   # coverage too low
])
def test_passes_gate(win, cov, ok):
    gate = {"win_rate_pct": 52, "coverage_pct": 30}
    assert passes_gate({"win_rate": win, "coverage": cov}, gate) is ok


def test_promotion_guard():
    # promote only if candidate >= max(52%, prod - 0.5pp)
    assert promotion_ok(0.60, prod_win_pct=0.60) is True    # >= 59.5
    assert promotion_ok(0.595, prod_win_pct=0.60) is True   # exactly prod-0.5pp
    assert promotion_ok(0.59, prod_win_pct=0.60) is False   # silent regression blocked
    assert promotion_ok(0.55, prod_win_pct=None) is True    # no prod -> only the 52% floor
    assert promotion_ok(0.51, prod_win_pct=None) is False   # below floor
