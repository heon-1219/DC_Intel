"""Market-intel ingestion dataclass. A fetcher yields RawIntel; the pipeline cleans,
extracts entities, dedups, clusters, scores, and persists into market_intel."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RawIntel:
    source: str                          # reddit|stocktwits|twitter|dcinside|naver|finnhub|newsapi
    author_handle: str
    url: str | None
    text: str                            # original post body (pre-clean)
    posted_at: datetime                  # tz-aware UTC
    symbols: list[str] = field(default_factory=list)   # cashtags/tickers found by the fetcher
    account_age_days: int | None = None  # for credibility E (None -> E=25)
    engagement: int | None = None        # karma / followers (credibility E)
    weak_label: str | None = None        # StockTwits self-tag: 'bullish'|'bearish' (sentiment §5.4)
