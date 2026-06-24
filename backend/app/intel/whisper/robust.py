"""Deterministic robust 1-D estimators for the whisper engine: weight-weighted median, normal-
consistent MAD, and MAD-based inlier selection. Pure (no I/O) so they unit-test exactly like
credibility.py / gate.py."""
from app.intel import whisper_config as cfg


def weighted_median(pairs: list[tuple[float, float]]) -> float | None:
    """Smallest value whose cumulative weight reaches half of the total weight (deterministic
    lower-value tie-break). Falls back to the plain lower-median when all weights <= 0. None if empty."""
    items = sorted(pairs, key=lambda p: p[0])
    if not items:
        return None
    total = sum(w for _, w in items)
    if total <= 0:
        vals = [v for v, _ in items]
        return vals[(len(vals) - 1) // 2]
    half = total / 2.0
    cum = 0.0
    for v, w in items:
        cum += w
        if cum >= half:
            return v
    return items[-1][0]


def scaled_mad(pairs: list[tuple[float, float]], center: float) -> float:
    """1.4826 × (weighted median of |value − center|). 0.0 when the inliers are identical."""
    if not pairs:
        return 0.0
    devs = [(abs(v - center), w) for v, w in pairs]
    m = weighted_median(devs)
    return 1.4826 * (m or 0.0)


def is_inlier(value: float, center: float, smad: float, mad_k: float | None = None) -> bool:
    """True if `value` is within mad_k scaled-MADs of the center. When the cluster is degenerate
    (smad == 0, i.e. all-identical) only an exactly-equal value is an inlier."""
    k = cfg.MAD_K if mad_k is None else mad_k
    if smad == 0:
        return value == center
    return abs(value - center) <= k * smad
