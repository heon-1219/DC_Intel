"""Tier-C whisper source: the durable free web path resolves to thewhispernumber.com/ticker/<symbol>
(this is what a websearch for "<TICKER> whisper number" surfaces first; raw DuckDuckGo scraping is
bot-blocked from datacenter IPs, so we fetch the result page directly). FREE, keyless; a browser UA.

The numbers are server-rendered (NOT JS-injected) in the <meta name="description"> headline, e.g.
  'AAPL (Apple Inc). whisper number: $1.99. consensus: $1.89. reports earnings Jul 30, 2026. ...'
A single regex yields whisper EPS + official consensus (anchor candidate) + earnings date. Parse is
pure + tested against the recorded REAL cassette (backend/tests/cassettes/whisper_websearch.html).
Best-effort: non-200 / no-meta yields no observation (fail-open)."""
import re
from datetime import date

import httpx

from app.intel import whisper_config as cfg
from app.intel.whisper.models import WhisperObservation
from app.intel.whisper.normalize import parse_eps

_BASE = "https://thewhispernumber.com/ticker"
_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
       "Accept": "text/html,application/xhtml+xml"}

_META = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.IGNORECASE)
_HEADLINE = re.compile(
    r"whisper number:\s*\$?(-?[0-9.]+)\.\s*consensus:\s*\$?(-?[0-9.]+)\."
    r"\s*reports earnings\s*([A-Za-z]+ [0-9]{1,2}, [0-9]{4})", re.IGNORECASE)


def parse_whispernumber(html: str, as_of: date) -> list[WhisperObservation]:
    """Pure: thewhispernumber ticker page HTML -> at most one WhisperObservation. `as_of` is the
    fetch date (the page is a live view, not a dated post)."""
    if not html:
        return []
    meta = _META.search(html)
    if not meta:
        return []
    headline = meta.group(1)
    m = _HEADLINE.search(headline)
    if not m:
        return []
    whisper = parse_eps(m.group(1))
    if whisper is None:
        return []
    consensus = parse_eps(m.group(2))
    return [WhisperObservation(
        value=whisper, raw_value=m.group(1), source="websearch",
        source_family=cfg.source_family("websearch"),
        source_credibility_prior=cfg.source_prior("websearch"),
        as_of_date=as_of, context_snippet=headline[:160], consensus_eps=consensus)]


class WhisperNumberFetcher:
    """Synchronous; self-disables on error."""
    name = "websearch"
    enabled = True

    def __init__(self, ticker: str | None = None, as_of: date | None = None):
        self.ticker = ticker
        self.as_of = as_of

    def fetch(self, source: str | None = None) -> list[WhisperObservation]:
        if not self.ticker:
            return []
        try:
            with httpx.Client(timeout=20, headers=_UA, follow_redirects=True) as c:
                r = c.get(f"{_BASE}/{self.ticker.lower()}")
            if r.status_code != 200:
                return []
            return parse_whispernumber(r.text, as_of=self.as_of or date.today())
        except Exception:  # noqa: BLE001 - best-effort
            return []
