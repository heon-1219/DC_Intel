"""Market-intel + sentiment tunables (market-intel-pipeline.md §13, env-overridable).
Spec calls this config/intel.py; in our layout Python config lives under app/intel/."""
import os


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# Credibility (§6)
INTEL_WEIGHTS = (0.30, 0.30, 0.25, 0.15)        # S, A, C, E
INTEL_COORDINATED_CAP = _i("INTEL_COORDINATED_CAP", 20)
# Source reputation tiers (S subscore). DC Inside / Naver = T4(30); news majors handled separately.
SOURCE_TIER = {
    "reddit": 70, "stocktwits": 70, "twitter": 50,
    "dcinside": 30, "naver": 30, "finnhub": 90, "newsapi": 70,
}

# Dedup / cluster (§4.3–§5.2)
INTEL_SIM_JOIN = _f("INTEL_SIM_JOIN", 0.80)
INTEL_SIM_NEARDUP = _f("INTEL_SIM_NEARDUP", 0.97)
INTEL_CONFIRM_SIM = _f("INTEL_CONFIRM_SIM", 0.70)
INTEL_CLUSTER_TTL_H = _i("INTEL_CLUSTER_TTL_H", 48)
INTEL_HASH_TTL_H = _i("INTEL_HASH_TTL_H", 48)
INTEL_SNIPPET_MAX_CHARS = _i("INTEL_SNIPPET_MAX_CHARS", 500)

# Retrieval / retention
INTEL_MIN_CREDIBILITY_DEFAULT = _i("INTEL_MIN_CREDIBILITY_DEFAULT", 25)
INTEL_RETENTION_DAYS = _i("INTEL_RETENTION_DAYS", 90)

# Anomaly (§9)
INTEL_ANOMALY_PCT = _f("INTEL_ANOMALY_PCT", 3.0)
INTEL_ANOMALY_WINDOW_MIN = _i("INTEL_ANOMALY_WINDOW_MIN", 30)
INTEL_ANOMALY_NEWS_QUIET_MIN = _i("INTEL_ANOMALY_NEWS_QUIET_MIN", 60)
INTEL_ANOMALY_COOLDOWN_MIN = _i("INTEL_ANOMALY_COOLDOWN_MIN", 120)
INTEL_RECENCY_HALFLIFE_H = _i("INTEL_RECENCY_HALFLIFE_H", 24)

# Scrape scope (config is the source of truth where docs disagree)
INTEL_SUBREDDITS = os.getenv(
    "INTEL_SUBREDDITS", "stocks,investing,wallstreetbets,StockMarket,options,Daytrading"
).split(",")
INTEL_KR_PAGE_BUDGET = _i("INTEL_KR_PAGE_BUDGET", 30)   # per 10-min cycle, DC+Naver combined

# Embedding + sentiment models
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
SENTIMENT_CLF_MODEL = os.getenv(
    "SENTIMENT_CLF_MODEL", "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")
SENTIMENT_CLF_MIN_CONF = _f("SENTIMENT_CLF_MIN_CONF", 0.45)
SENTIMENT_MIN_TEXT_LEN = _i("SENTIMENT_MIN_TEXT_LEN", 10)
SENTIMENT_ACTIVE_STOCK_CAP = _i("SENTIMENT_ACTIVE_STOCK_CAP", 50)
