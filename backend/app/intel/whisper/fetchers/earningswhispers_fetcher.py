"""Tier-A whisper source: earningswhispers.com clean JSON API (GET /api/epsdetails/<TICKER>).

The /stocks/<TICKER> HTML page is JS-rendered (empty placeholders) — do NOT scrape it. The real
data is a small ~2KB application/json document that the site's own stocks.js fetches. FREE, keyless;
needs only a browser UA + Referer (same UA fix the intel scrapers use). Best-effort: any non-200 or
parse error yields no observation (fail-open, like retry.py / the intel fetchers). Parse is pure +
tested against the recorded REAL cassette (backend/tests/cassettes/whisper_earningswhispers.json).

Field map (verified on the recorded NVDA payload):
  whisper   -> the whisper EPS (WhisperObservation.value)
  estimate  -> official consensus EPS (anchor candidate -> consensus_eps)
  epsDate   -> ISO datetime of the report (as_of_date)
  quarter   -> human label
Sentinel: -999.0 (seen in ewGrade/pwrRating, and possibly whisper/estimate) is treated as null."""
from datetime import date, datetime

import httpx

from app.intel import whisper_config as cfg
from app.intel.whisper.models import WhisperObservation

_BASE = "https://www.earningswhispers.com/api/epsdetails"
_UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.earningswhispers.com/stocks/",
    "X-Requested-With": "XMLHttpRequest",
}
_SENTINEL = -999.0


def _num(v):
    """A real EPS number, or None for missing / the -999.0 sentinel / non-numeric."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f == _SENTINEL else f


def _as_of(eps_date: str | None) -> date | None:
    if not eps_date:
        return None
    try:
        return datetime.fromisoformat(eps_date.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_earningswhispers(data: dict) -> list[WhisperObservation]:
    """Pure: one earningswhispers payload -> at most one WhisperObservation (empty when no whisper)."""
    if not isinstance(data, dict):
        return []
    whisper = _num(data.get("whisper"))
    eps_date = _as_of(data.get("epsDate"))
    if whisper is None or eps_date is None:
        return []
    consensus = _num(data.get("estimate"))
    quarter = (data.get("quarter") or "").strip() or None
    return [WhisperObservation(
        value=whisper, raw_value=str(data.get("whisper")), source="earningswhispers",
        source_family=cfg.source_family("earningswhispers"),
        source_credibility_prior=cfg.source_prior("earningswhispers"),
        as_of_date=eps_date, context_snippet=(data.get("subject") or "")[:120],
        quarter=quarter, consensus_eps=consensus)]


class EarningsWhispersFetcher:
    """Synchronous (the engine calls fetch() inline). Self-disables on any error."""
    name = "earningswhispers"
    enabled = True

    def __init__(self, ticker: str | None = None):
        self.ticker = ticker

    def fetch(self, source: str | None = None) -> list[WhisperObservation]:
        if not self.ticker:
            return []
        try:
            with httpx.Client(timeout=20, headers=_UA) as c:
                r = c.get(f"{_BASE}/{self.ticker.upper()}")
            if r.status_code != 200:
                return []
            return parse_earningswhispers(r.json())
        except Exception:  # noqa: BLE001 - best-effort; a failed source never aborts the run
            return []
