"""Tier-B whisper source: Estimize — SCAFFOLD ONLY (intentionally unavailable for whisper values).

Recon outcome: the static estimize.com/<ticker> page is server-rendered and yields real earnings
DATE / quarter metadata (a JSON blob in a <div data="...">), but the actual EPS estimate values
(Estimize crowd consensus + Wall Street consensus) are loaded by a separate XHR that returns HTTP 202
behind an AWS WAF bot challenge (`x-amzn-waf-action: challenge`) from this datacenter IP. Solving it
needs a headless browser / challenge solver, which conflicts with the FREE + local-first owner
standards. Per owner standard #4 we do NOT fabricate the missing EPS numbers, so NO cassette exists
and there is no offline parse test — only a @live skeleton (test_whisper_live.py) documenting the
blocker. This fetcher therefore self-disables and never emits an observation; AIWCE relies on Tier A
(earningswhispers) + Tier C (websearch) + Tier D (stocktwits) instead.

To revisit: if a free, WAF-free metadata-only path is ever wired, parse the <div data="..."> blob
(html.unescape -> json.JSONDecoder().raw_decode) and pick the release where current==true to resolve
quarter+date only — the EPS values remain WAF-gated."""
from datetime import date

from app.intel.whisper.models import WhisperObservation


class EstimizeFetcher:
    """Synchronous, self-disabled (enabled=False): EPS values are WAF-gated, see module docstring."""
    name = "estimize"
    enabled = False

    def __init__(self, ticker: str | None = None, as_of: date | None = None):
        self.ticker = ticker
        self.as_of = as_of

    def fetch(self, source: str | None = None) -> list[WhisperObservation]:
        return []   # disabled — never emits (no FREE, non-WAF path to the estimate values)
