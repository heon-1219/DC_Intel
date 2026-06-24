"""AIWCE source fetchers + the MultiSourceFetcher the engine consumes.

The engine calls `fetcher.fetch(source)` SYNCHRONOUSLY once per source in the ladder
(earningswhispers/estimize -> websearch -> forum/stocktwits). MultiSourceFetcher dispatches each
source name to the matching real fetcher (one per ticker), so a single injected object serves the
whole convergence loop. Each per-source fetcher self-disables on error (fail-open), so a dead source
never aborts the run. build_default_fetcher() wires the production set for the scheduled job; tests
inject a FakeFetcher instead."""
from datetime import date

from app.intel.whisper.fetchers.earningswhispers_fetcher import EarningsWhispersFetcher
from app.intel.whisper.fetchers.estimize_fetcher import EstimizeFetcher
from app.intel.whisper.fetchers.stocktwits_fetcher import StockTwitsWhisperFetcher
from app.intel.whisper.fetchers.websearch_fetcher import WhisperNumberFetcher


class MultiSourceFetcher:
    """Routes `fetch(source)` to the per-source fetcher; unknown/disabled sources return []."""

    def __init__(self, by_source: dict):
        self.by_source = by_source

    def fetch(self, source: str) -> list:
        f = self.by_source.get(source)
        if f is None or not getattr(f, "enabled", True):
            return []
        return f.fetch(source) or []


def build_default_fetcher(symbol: str, exchange: str, earnings_date: date) -> MultiSourceFetcher:
    """The production fetcher set for one upcoming-earnings ticker (US whisper sources are
    ticker-keyed; KR is not covered by these US-centric sources). `as_of` for the live-view sources
    (websearch/stocktwits) is today, set inside fetch()."""
    return MultiSourceFetcher({
        "earningswhispers": EarningsWhispersFetcher(ticker=symbol),
        "estimize": EstimizeFetcher(ticker=symbol),            # disabled (WAF-gated)
        "websearch": WhisperNumberFetcher(ticker=symbol),
        "forum": StockTwitsWhisperFetcher(ticker=symbol),      # 'forum' family alias for stocktwits
        "stocktwits": StockTwitsWhisperFetcher(ticker=symbol),
    })
