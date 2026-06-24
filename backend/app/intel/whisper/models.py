"""Frozen dataclasses for the whisper engine (mirror app/intel/models.py + app/calendar/models.py).
Pure transforms return NEW instances via dataclasses.replace — nothing mutates in place."""
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class WhisperObservation:
    value: float | None
    raw_value: str
    source: str
    source_family: str
    source_credibility_prior: float
    as_of_date: date
    context_snippet: str = ""
    quarter: str | None = None
    # derived (None until the weight pass fills them)
    age_days: int | None = None
    recency_weight: float | None = None
    rel_dev: float | None = None
    weight: float | None = None
    kept: bool = True
    reject_reason: str | None = None  # None == kept inlier; else stale|implausible|unparsed|mad_outlier|near_dup


@dataclass(frozen=True)
class WhisperPrior:
    mu0: float                 # official consensus EPS — the trustworthy anchor
    anchor_scale: float        # max(|mu0|, MIN_SCALE) — scale-free unit for relative thresholds
    earnings_date: date
    consensus_source: str = "finnhub"


@dataclass(frozen=True)
class WhisperCluster:
    value: float               # weighted-median center
    members: tuple             # tuple[WhisperObservation, ...]
    n_distinct_families: int
    support_mass: float        # sum of member weights
    weighted_dispersion: float # scaled-MAD / anchor_scale (dimensionless)
    coordinated: bool = False


@dataclass(frozen=True)
class WhisperResult:
    whisper_value: float | None
    confidence: int            # 0..100
    status: str                # corroborated | tentative | no_reliable_whisper
    anchor: float | None
    surprise_vs_anchor: float | None
    inlier_dispersion: float | None
    n_inliers: int
    n_outliers_rejected: int
    n_distinct_families: int
    contributing_families: tuple
    factors: dict              # f_count/f_agree/f_cred/f_recency/f_anchor + applied caps (audit)
    rounds_used: int
    abstain_reason: str | None
    computed_at: datetime | None = None
