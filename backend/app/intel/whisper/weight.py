"""Anchor construction + the per-observation guard/weight pass. Each `evaluate` returns a NEW frozen
observation with derived fields filled and kept/reject_reason set. Pure — no I/O.

Note: a profit<->loss sign flip vs the consensus almost always trips the anchor-plausibility gate
first (a flip implies rel_dev >= 1.0 > ABSURD_REL), so SIGN_PENALTY is a secondary guard kept for the
rare near-zero-anchor case."""
from dataclasses import replace
from datetime import date

from app.intel import whisper_config as cfg
from app.intel.whisper.models import WhisperObservation, WhisperPrior


def build_prior(consensus_eps: float | None, earnings_date: date | None,
                source: str = "finnhub") -> WhisperPrior | None:
    """The trustworthy anchor. None when consensus or earnings date is missing (engine then abstains
    with NO_ANCHOR / NO_EARNINGS_DATE — we never invent a prior)."""
    if consensus_eps is None or earnings_date is None:
        return None
    scale = max(abs(float(consensus_eps)), cfg.MIN_SCALE)
    return WhisperPrior(mu0=float(consensus_eps), anchor_scale=scale,
                        earnings_date=earnings_date, consensus_source=source)


def _plausibility(rel_dev: float) -> float:
    if rel_dev <= cfg.ABSURD_REL_SOFT:
        return 1.0
    if rel_dev >= cfg.ABSURD_REL:
        return 0.0
    return (cfg.ABSURD_REL - rel_dev) / (cfg.ABSURD_REL - cfg.ABSURD_REL_SOFT)  # linear 1->0


def _recency(age_days: int) -> float:
    return 0.5 ** (max(0, age_days) / cfg.RECENCY_HALFLIFE_D)


def evaluate(obs: WhisperObservation, prior: WhisperPrior, today: date) -> WhisperObservation:
    """Guard + weight one observation against the anchor."""
    if obs.value is None:
        return replace(obs, kept=False, reject_reason="unparsed", weight=0.0)

    # quarter / recency guard — a whisper is PRE-report and within one earnings cycle
    if obs.as_of_date > prior.earnings_date:  # dated after the report => it's the ACTUAL, not a whisper
        return replace(obs, kept=False, reject_reason="stale", weight=0.0)
    if (prior.earnings_date - obs.as_of_date).days > cfg.STALE_WINDOW_DAYS:
        return replace(obs, kept=False, reject_reason="stale", weight=0.0)

    age_days = (today - obs.as_of_date).days
    recency = _recency(age_days)

    # anchor-plausibility gate
    rel_dev = abs(obs.value - prior.mu0) / prior.anchor_scale
    if rel_dev > cfg.ABSURD_REL:
        return replace(obs, kept=False, reject_reason="implausible", rel_dev=rel_dev,
                       age_days=age_days, recency_weight=recency, weight=0.0)
    plaus = _plausibility(rel_dev)
    sign_ok = 1.0 if (obs.value >= 0) == (prior.mu0 >= 0) else cfg.SIGN_PENALTY

    weight = obs.source_credibility_prior * recency * plaus * sign_ok
    return replace(obs, kept=True, reject_reason=None, rel_dev=rel_dev, age_days=age_days,
                   recency_weight=recency, weight=weight)
