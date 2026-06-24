"""Orchestrator: build/accept the anchor, then run the budgeted, convergence-driven retrieval loop
over the source ladder (A=earningswhispers/estimize -> B=websearch -> C=forum/stocktwits), folding
each tier's observations into the same corroboration pipeline. Stops early on confirmation (don't
dilute a clean signal) or no-gain, hard-stops at budget. Fetchers are INJECTED — a FakeFetcher replays
recorded cassettes in tests. The only side effect is fetcher.fetch(); all decisions are the pure modules."""
from datetime import date, datetime

from app.intel import whisper_config as cfg
from app.intel.whisper.cluster import cluster_values, refine_inliers
from app.intel.whisper.models import WhisperResult
from app.intel.whisper.score import classify, dominance, meaningfulness
from app.intel.whisper.weight import evaluate

DEFAULT_TIERS = [["earningswhispers", "estimize"], ["websearch"], ["forum", "stocktwits"]]


def _abstain(reason, prior, rounds, computed_at=None) -> WhisperResult:
    return WhisperResult(
        whisper_value=None, confidence=0, status="no_reliable_whisper",
        anchor=(prior.mu0 if prior else None), surprise_vs_anchor=None, inlier_dispersion=None,
        n_inliers=0, n_outliers_rejected=0, n_distinct_families=0, contributing_families=(),
        factors={}, rounds_used=rounds, abstain_reason=reason, computed_at=computed_at)


def _high_trust_override(kept_obs, prior):
    """A single fresh, plausible EarningsWhispers obs may still emit as tentative (capped) — that one
    purpose-built source beats nothing, but is flagged thin."""
    cands = [o for o in kept_obs
             if o.source_family == "earningswhispers"
             and o.source_credibility_prior >= cfg.HIGH_TRUST_PRIOR
             and (o.age_days if o.age_days is not None else 999) <= cfg.HIGH_TRUST_MAX_AGE_D
             and (o.rel_dev if o.rel_dev is not None else 1.0) <= cfg.ABSURD_REL_SOFT]
    return cands[0] if cands else None


def _assess(kept_obs, raw_total, prior, rounds, computed_at=None) -> WhisperResult:
    if raw_total == 0:
        return _abstain("NO_OBSERVATIONS", prior, rounds, computed_at)
    if not kept_obs:
        return _abstain("ALL_FILTERED", prior, rounds, computed_at)

    clusters = cluster_values(kept_obs, prior.anchor_scale)
    if not clusters:
        return _abstain("ALL_FILTERED", prior, rounds, computed_at)
    winner, runner_up = clusters[0], (clusters[1] if len(clusters) > 1 else None)
    dom = dominance(winner, runner_up)
    center, inliers, n_out, disp, n_fam = refine_inliers(winner, prior.anchor_scale)

    if len(inliers) < cfg.MIN_OBS:
        ht = _high_trust_override(kept_obs, prior)
        if ht is not None:
            conf, factors = meaningfulness([ht], ht.value, 0.0, 1, False, prior)
            return WhisperResult(
                whisper_value=round(ht.value, 2), confidence=min(conf, cfg.SINGLE_FAMILY_CAP),
                status="tentative", anchor=prior.mu0, surprise_vs_anchor=round(ht.value - prior.mu0, 4),
                inlier_dispersion=0.0, n_inliers=1, n_outliers_rejected=0, n_distinct_families=1,
                contributing_families=("earningswhispers",), factors=factors, rounds_used=rounds,
                abstain_reason=None, computed_at=computed_at)
        return _abstain("INSUFFICIENT_INLIERS", prior, rounds, computed_at)

    if disp > cfg.WIDE_DISP:
        return _abstain("NO_AGREEMENT", prior, rounds, computed_at)
    if runner_up is not None and runner_up.support_mass >= cfg.DOMINANCE_FRACTION * winner.support_mass:
        return _abstain("UNRESOLVED_CONTENTION", prior, rounds, computed_at)
    if abs(center - prior.mu0) / prior.anchor_scale > cfg.ABSURD_REL:
        return _abstain("ANCHOR_DISTRUST", prior, rounds, computed_at)

    conf, factors = meaningfulness(inliers, center, disp, n_fam, winner.coordinated, prior)
    status = classify(conf, n_fam, winner.coordinated, dom, disp)
    if status == "no_reliable_whisper":
        return _abstain("COORDINATED" if winner.coordinated else "LOW_CONFIDENCE", prior, rounds, computed_at)

    return WhisperResult(
        whisper_value=round(center, 2), confidence=conf, status=status, anchor=prior.mu0,
        surprise_vs_anchor=round(center - prior.mu0, 4), inlier_dispersion=round(disp, 4),
        n_inliers=len(inliers), n_outliers_rejected=n_out, n_distinct_families=n_fam,
        contributing_families=tuple(sorted({m.source_family for m in inliers})), factors=factors,
        rounds_used=rounds, abstain_reason=None, computed_at=computed_at)


def corroborate(prior, fetcher, today: date, tiers=None, computed_at: datetime | None = None) -> WhisperResult:
    """Run the convergence loop. `fetcher.fetch(source)` -> list[WhisperObservation] (value pre-parsed).
    A None prior means the caller had no anchor -> NO_ANCHOR abstention."""
    if prior is None:
        return _abstain("NO_ANCHOR", None, 0, computed_at)
    tiers = tiers or DEFAULT_TIERS
    kept_obs: list = []
    raw_total = rounds = fetched = 0
    last = _abstain("NO_OBSERVATIONS", prior, 0, computed_at)

    for idx, tier_sources in enumerate(tiers):
        if rounds >= cfg.MAX_ROUNDS or fetched >= cfg.SOURCE_BUDGET:
            break
        rounds += 1
        new_kept = 0
        for src in tier_sources:
            if fetched >= cfg.SOURCE_BUDGET:
                break
            fetched += 1
            try:
                raws = fetcher.fetch(src) or []
            except Exception:  # noqa: BLE001 - best-effort; a failed source never aborts the run
                raws = []
            raw_total += len(raws)
            for o in raws:
                ev = evaluate(o, prior, today)
                if ev.kept:
                    kept_obs.append(ev)
                    new_kept += 1

        last = _assess(kept_obs, raw_total, prior, rounds, computed_at)
        if last.status == "corroborated":
            return last                 # STOP-CONFIRM — a clean signal must not be diluted by noisier tiers
        if idx > 0 and new_kept == 0:
            break                       # STOP-NO-GAIN — round added no new inliers
    return last
