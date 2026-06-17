"""NewsAPI /v2/everything fetcher (sentiment-pipeline.md §10). Implements the same SourceFetcher
protocol as the social fetchers so it plugs into app.intel.scraper.ingest. Best-effort: a non-200
is treated as 'no data' (never raised). parse_newsapi is pure for offline testing."""
from datetime import datetime, timezone

import httpx

from app.intel.models import RawIntel

_BASE = "https://newsapi.org/v2/everything"
_PER_RUN = 20   # top-N tracked tickers per cycle (rate budget)
_PAGE_SIZE = 20


def _dt(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_newsapi(data: dict) -> list[RawIntel]:
    """Map a NewsAPI /v2/everything response to RawIntel. Skips articles with no title."""
    out: list[RawIntel] = []
    for art in (data or {}).get("articles", []) or []:
        title = (art.get("title") or "").strip()
        if not title:
            continue
        posted = _dt(art.get("publishedAt"))
        if posted is None:
            continue
        description = (art.get("description") or "").strip()
        text = (title + ". " + description).strip()
        source_name = ((art.get("source") or {}).get("name")) or "newsapi"
        out.append(RawIntel(
            source="newsapi",
            author_handle=source_name,
            url=art.get("url"),
            text=text,
            posted_at=posted))
    return out


class NewsApiFetcher:
    name = "newsapi"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def fetch(self, symbols: list[str]) -> list[RawIntel]:
        if not self.enabled:
            return []
        out: list[RawIntel] = []
        async with httpx.AsyncClient(timeout=20) as c:
            for sym in symbols[:_PER_RUN]:
                try:
                    r = await c.get(_BASE, params={
                        "q": sym, "language": "en", "sortBy": "publishedAt",
                        "pageSize": _PAGE_SIZE, "apiKey": self.api_key})
                    if r.status_code == 200:
                        out.extend(parse_newsapi(r.json()))
                except Exception:  # noqa: BLE001 - best-effort per symbol, never abort the run
                    continue
        return out
