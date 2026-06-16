"""Credibility scoring (market-intel-pipeline.md §6). Pure: credibility = round(0.30·S +
0.30·A + 0.25·C + 0.15·E), capped at 20 for coordinated clusters, clamped [0,100]."""
import math

from app.intel.config import INTEL_COORDINATED_CAP, INTEL_WEIGHTS, SOURCE_TIER

# Tier-1 news outlets (S=90); other outlets S=70. Matched as substrings of the author handle
# (news rows use the outlet domain as author_handle, e.g. "reuters.com", "yna.co.kr").
_NEWS_MAJORS = ("reuters", "bloomberg", "yonhap", "yna.", "연합뉴스", "maeil", "mk.co", "매일경제")


def subscore_s(source: str, author_handle: str | None = None) -> int:
    """Source reputation tier."""
    if source in ("finnhub", "newsapi"):
        h = (author_handle or "").lower()
        return 90 if any(m in h for m in _NEWS_MAJORS) else 70
    return SOURCE_TIER.get(source, 30)


def subscore_a(resolved: int | None, confirmed: int | None) -> float:
    """Laplace-smoothed author confirmation rate; unknown author -> 50."""
    if resolved is None:
        return 50.0
    return 100.0 * ((confirmed or 0) + 1) / (resolved + 2)


def subscore_c(distinct_authors: int) -> float:
    """Corroboration: distinct (source, author) pairs in the cluster."""
    return min(100.0, 25.0 * (distinct_authors - 1))


def subscore_e(age_days: int | None, engagement: int | None) -> int:
    """Account age + engagement; 25 when no profile data at all."""
    if age_days is None and engagement is None:
        return 25
    age_part = min(1.0, (age_days or 0) / 365)
    engagement_part = min(1.0, math.log10(1 + (engagement or 0)) / 5)
    return round(50 * age_part + 50 * engagement_part)


def credibility(s: float, a: float, c: float, e: float, *, coordinated: bool = False) -> int:
    ws, wa, wc, we = INTEL_WEIGHTS
    val = round(ws * s + wa * a + wc * c + we * e)
    if coordinated:
        val = min(val, INTEL_COORDINATED_CAP)
    return max(0, min(100, val))


def band(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "moderate"
    if score >= 25:
        return "low"
    return "very_low"
