"""Tier-D whisper source: StockTwits public stream (api.stocktwits.com/api/2/streams/symbol/<T>.json).
FREE, keyless, reachable with a browser UA. Per recon this is the NOISIEST tier — the numeric chatter
is overwhelmingly PRICE/option flow ('Call Wall: $390', 'Put Wall: $380', share-price targets), NOT
EPS. So the extractor is deliberately conservative: it surfaces a number ONLY when an EPS cue word
('eps' / 'whisper' / 'estimate' / 'earnings ... per share') sits next to it, and even then the
anchor-plausibility gate + PLAUSIBLE_ABS_CAP discard price-sized numbers. Its real value is exercising
the engine's noise-rejection, never supplying a primary whisper.

Parse is pure + tested against the recorded REAL cassette (backend/tests/cassettes/whisper_stocktwits.json,
the AVGO snapshot chosen for its dense numeric free-text). Best-effort: non-200 yields no data."""
import html as _html
import re
from datetime import date, datetime

import httpx

from app.intel import whisper_config as cfg
from app.intel.whisper.models import WhisperObservation
from app.intel.whisper.normalize import parse_eps

_BASE = "https://api.stocktwits.com/api/2/streams/symbol"
_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
       "Accept": "application/json"}

# An EPS cue immediately followed (within a few tokens) by a number, OR a number then a cue.
# 'eps', 'whisper', 'estimate', or 'earnings ... per share'. A number = optional $, digits, decimals.
_NUM = r"\$?-?\d+(?:\.\d+)?c?"
_CUE = r"(?:eps|whisper|estimate|earnings per share|per share)"
_CUE_THEN_NUM = re.compile(rf"{_CUE}[^.\d]{{0,18}}({_NUM})", re.IGNORECASE)
_NUM_THEN_CUE = re.compile(rf"({_NUM})\s*{_CUE}", re.IGNORECASE)


def _dt(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_eps_candidates(text: str) -> list[str]:
    """Raw EPS-context number strings from one message body (cue-gated)."""
    t = _html.unescape(text or "")
    found: list[str] = []
    for pat in (_CUE_THEN_NUM, _NUM_THEN_CUE):
        found.extend(m.group(1) for m in pat.finditer(t))
    return found


def parse_stocktwits_whisper(data: dict, as_of: date) -> list[WhisperObservation]:
    """Pure: a stocktwits stream payload -> zero or more EPS-candidate observations. Price/option
    numbers either fail the cue gate or exceed PLAUSIBLE_ABS_CAP in parse_eps and are dropped."""
    if not isinstance(data, dict):
        return []
    out: list[WhisperObservation] = []
    for m in data.get("messages", []) or []:
        body = m.get("body") or ""
        posted = _dt(m.get("created_at"))
        obs_date = posted.date() if posted else as_of
        handle = ((m.get("user") or {}).get("username")) or "unknown"
        for cand in _extract_eps_candidates(body):
            value = parse_eps(cand)               # None for price-sized magnitudes / non-EPS
            if value is None:
                continue
            out.append(WhisperObservation(
                value=value, raw_value=cand, source="stocktwits",
                source_family=cfg.source_family("stocktwits"),
                source_credibility_prior=cfg.source_prior("stocktwits"),
                as_of_date=obs_date, context_snippet=_html.unescape(body)[:120],
                quarter=None))
    return out


class StockTwitsWhisperFetcher:
    """Synchronous; self-disables on error. Token optional (raises the rate limit)."""
    name = "stocktwits"
    enabled = True

    def __init__(self, ticker: str | None = None, as_of: date | None = None,
                 access_token: str = ""):
        self.ticker = ticker
        self.as_of = as_of
        self.access_token = access_token

    def fetch(self, source: str | None = None) -> list[WhisperObservation]:
        if not self.ticker:
            return []
        params = {"access_token": self.access_token} if self.access_token else None
        try:
            with httpx.Client(timeout=20, headers=_UA) as c:
                r = c.get(f"{_BASE}/{self.ticker.upper()}.json", params=params)
            if r.status_code != 200:
                return []
            return parse_stocktwits_whisper(r.json(), as_of=self.as_of or date.today())
        except Exception:  # noqa: BLE001 - best-effort
            return []
