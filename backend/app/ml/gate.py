"""Ship-gate, neutral rule, displayed confidence, and promotion guard
(prediction-model.md §5.3 / §5.4 / §7.6). Pure math — no ML libs, no I/O — so it is shared
by training (gate a candidate), M6 serving (neutral rule + confidence), and M7 (grading)."""

_DIRECTIONS = ("up", "down", "neutral")


def apply_neutral_rule(probs: dict, tau_dir: float) -> tuple[str, bool]:
    """§5.3: displayed = argmax; if displayed is up/down but max(p_up,p_down) < tau_dir, downgrade
    to neutral. Returns (displayed_direction, neutral_rule_applied)."""
    displayed = max(_DIRECTIONS, key=lambda d: probs[d])
    if displayed in ("up", "down") and max(probs["up"], probs["down"]) < tau_dir:
        return "neutral", True
    return displayed, False


def confidence(p_displayed: float, *, any_stale: bool, cap: int = 65) -> int:
    """§5.4: round(100 × P(displayed)); cap at `cap` when any feeding data is stale."""
    c = round(100 * p_displayed)
    return min(c, cap) if any_stale else c


def directional_metrics(rows: list[tuple[str, str]]) -> dict:
    """§7.6: rows = [(displayed, realized), ...] AFTER calibration + neutral rule. A directional
    call is displayed up/down; a realized 'neutral' is a LOSS for a directional call."""
    n_total = len(rows)
    directional = [(d, r) for d, r in rows if d in ("up", "down")]
    n_dir = len(directional)
    wins = sum(1 for d, r in directional if r == d)
    return {
        "n_total": n_total, "n_directional": n_dir, "wins": wins,
        "win_rate": (wins / n_dir) if n_dir else 0.0,
        "coverage": (n_dir / n_total) if n_total else 0.0,
    }


def passes_gate(metrics: dict, gate_cfg: dict) -> bool:
    """§7.6: directional win rate >= win_rate_pct AND coverage >= coverage_pct (inclusive)."""
    return (metrics["win_rate"] * 100 >= gate_cfg["win_rate_pct"]
            and metrics["coverage"] * 100 >= gate_cfg["coverage_pct"])


def promotion_ok(candidate_win: float, *, prod_win_pct: float | None,
                 margin_pp: float = 0.5, gate_win_pct: float = 52.0) -> bool:
    """§7.7 promotion guard: promote only if candidate >= max(gate floor, prod - margin_pp).
    `candidate_win`/`prod_win_pct` are fractions (0..1); gate/margin are in percentage points."""
    floor_pct = gate_win_pct if prod_win_pct is None else max(gate_win_pct,
                                                              prod_win_pct * 100 - margin_pp)
    return candidate_win * 100 >= floor_pct
