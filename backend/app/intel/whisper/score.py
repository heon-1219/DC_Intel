"""Meaningfulness scoring + status classification for the whisper engine. Pure.

confidence = round(100 · f_count · f_agree · f_cred · f_recency · f_anchor) — MULTIPLICATIVE, so any
weak dimension caps the whole (you can't buy a score by being loud — the 'weakest link forces honesty'
spirit of the coordinated-cap and the 52% gate). Then hard caps (coordinated/single-family/stale/
anchor-only) mirror gate.py. Bands reuse the credibility 50/75 boundaries."""
from app.intel import whisper_config as cfg


def dominance(winner, runner_up) -> float:
    """1 − support(runner_up)/support(winner), clamped to [0,1]. 1.0 when there's no contender."""
    if runner_up is None or winner.support_mass <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - runner_up.support_mass / winner.support_mass))


def meaningfulness(inliers, center, inlier_dispersion, n_distinct_families, coordinated, prior):
    """Return (confidence:int 0..100, factors:dict). `factors` records the five components + any caps
    applied, for auditability."""
    weights = [(m.weight or 0.0) for m in inliers]
    wsum = sum(weights)
    priors = [m.source_credibility_prior for m in inliers]
    recencies = [(m.recency_weight or 0.0) for m in inliers]

    f_count = min(1.0, n_distinct_families / cfg.TARGET_FAMILIES)
    f_agree = max(0.0, min(1.0, 1.0 - inlier_dispersion / cfg.WIDE_DISP))
    max_prior = max(priors) if priors else 0.0
    wmean_prior = (sum(p * w for p, w in zip(priors, weights)) / wsum) if wsum > 0 else (
        (sum(priors) / len(priors)) if priors else 0.0)
    f_cred = 0.6 * max_prior + 0.4 * wmean_prior
    f_recency = (sum(r * w for r, w in zip(recencies, weights)) / wsum) if wsum > 0 else (
        (sum(recencies) / len(recencies)) if recencies else 0.0)
    rel_dev_center = abs(center - prior.mu0) / prior.anchor_scale
    f_anchor = max(0.25, min(1.0, 1.0 - rel_dev_center / cfg.ABSURD_REL))

    raw = f_count * f_agree * f_cred * f_recency * f_anchor
    confidence = round(100 * raw)
    caps: list[str] = []

    if coordinated:
        confidence = min(confidence, cfg.COORDINATED_CAP); caps.append("coordinated")
    if n_distinct_families == 1:
        confidence = min(confidence, cfg.SINGLE_FAMILY_CAP); caps.append("single_family")
    if inliers and all((m.age_days or 0) > cfg.CAP_AGE_D for m in inliers):
        confidence = min(confidence, cfg.STALE_CAP); caps.append("stale")
    # anchor-only guard: a no-shift number from no purpose-built source must not pose as a discovered edge
    shift = abs(center - prior.mu0)
    floor_shift = cfg.SHIFT_MIN * prior.anchor_scale
    families = {m.source_family for m in inliers}
    if shift < floor_shift and families.isdisjoint(cfg.PURPOSE_BUILT):
        scale = (shift / floor_shift) if floor_shift > 0 else 0.0
        confidence = round(confidence * scale); caps.append("anchor_only")

    confidence = max(0, min(100, confidence))
    factors = {"f_count": round(f_count, 4), "f_agree": round(f_agree, 4), "f_cred": round(f_cred, 4),
               "f_recency": round(f_recency, 4), "f_anchor": round(f_anchor, 4), "caps": caps}
    return confidence, factors


def classify(confidence, n_distinct_families, coordinated, dom, inlier_dispersion) -> str:
    """corroborated (blue) | tentative (amber) | no_reliable_whisper (none)."""
    if (confidence >= cfg.CORROB_FLOOR and n_distinct_families >= cfg.N_CONF and not coordinated
            and dom >= cfg.DOMINANCE_MIN and inlier_dispersion <= cfg.WIDE_DISP):
        return "corroborated"
    if confidence >= cfg.CONF_FLOOR:
        return "tentative"
    return "no_reliable_whisper"
