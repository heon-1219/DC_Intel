"""Tunables for the whisper corroboration engine (AIWCE), env-overridable via the _f/_i helpers
(same pattern as other config modules). Thresholds reuse the project's credibility band boundaries
(50/75) and gate-style confidence caps. See docs/superpowers/plans/2026-06-24-whisper-corroboration-engine.md."""
import os


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return int(default)


# --- iteration budget ---
LOOKAHEAD_DAYS = _i("WHISPER_LOOKAHEAD_DAYS", 21)
MAX_ROUNDS = _i("WHISPER_MAX_ROUNDS", 4)
SOURCE_BUDGET = _i("WHISPER_SOURCE_BUDGET", 8)
MOVE_EPS = _f("WHISPER_MOVE_EPS", 0.01)

# --- agreement / dispersion ---
TIGHT_DISP = _f("WHISPER_TIGHT_DISP", 0.04)
WIDE_DISP = _f("WHISPER_WIDE_DISP", 0.12)
MIN_OBS = _i("WHISPER_MIN_OBS", 3)
N_CONF = _i("WHISPER_N_CONF", 2)
TARGET_FAMILIES = _i("WHISPER_TARGET_FAMILIES", 3)
MAD_K = _f("WHISPER_MAD_K", 3.0)
AGREE_ABS_TOL = _f("WHISPER_AGREE_ABS_TOL", 0.01)
AGREE_REL_TOL = _f("WHISPER_AGREE_REL_TOL", 0.02)
DOMINANCE_FRACTION = _f("WHISPER_DOMINANCE_FRACTION", 0.6)
DOMINANCE_MIN = _f("WHISPER_DOMINANCE_MIN", 0.5)

# --- plausibility vs the consensus anchor ---
ABSURD_REL = _f("WHISPER_ABSURD_REL", 0.60)
ABSURD_REL_SOFT = _f("WHISPER_ABSURD_REL_SOFT", 0.30)
MIN_SCALE = _f("WHISPER_MIN_SCALE", 0.10)
PLAUSIBLE_ABS_CAP = _f("WHISPER_PLAUSIBLE_ABS_CAP", 100.0)
SIGN_PENALTY = _f("WHISPER_SIGN_PENALTY", 0.4)
SHIFT_MIN = _f("WHISPER_SHIFT_MIN", 0.02)

# --- recency / staleness ---
RECENCY_HALFLIFE_D = _f("WHISPER_RECENCY_HALFLIFE_D", 14)
STALE_WINDOW_DAYS = _i("WHISPER_STALE_WINDOW_DAYS", 45)
CAP_AGE_D = _i("WHISPER_CAP_AGE_D", 21)

# --- confidence floors / caps (mirror credibility.band + gate caps) ---
CONF_FLOOR = _i("WHISPER_CONF_FLOOR", 55)
CORROB_FLOOR = _i("WHISPER_CORROB_FLOOR", 75)
SINGLE_FAMILY_CAP = _i("WHISPER_SINGLE_FAMILY_CAP", 40)
STALE_CAP = _i("WHISPER_STALE_CAP", 65)
COORDINATED_CAP = _i("WHISPER_COORDINATED_CAP", 20)
HIGH_TRUST_PRIOR = _f("WHISPER_HIGH_TRUST_PRIOR", 0.85)
HIGH_TRUST_MAX_AGE_D = _i("WHISPER_HIGH_TRUST_MAX_AGE_D", 7)

# --- source priors + family mapping (independence is counted by FAMILY, not row) ---
SOURCE_TIER = {
    "earningswhispers": 0.85,
    "estimize": 0.75,
    "websearch": 0.45,
    "forum": 0.30,
    "stocktwits": 0.30,
}
SOURCE_FAMILY = {
    "earningswhispers": "earningswhispers",
    "estimize": "estimize",
    "websearch": "websearch",
    "forum": "forum",
    "stocktwits": "forum",
}
PURPOSE_BUILT = frozenset({"earningswhispers", "estimize"})


def source_family(source: str) -> str:
    return SOURCE_FAMILY.get(source, "forum")


def source_prior(source: str) -> float:
    return SOURCE_TIER.get(source, 0.30)
