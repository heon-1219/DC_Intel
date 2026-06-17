"""Finnhub company-news fetcher (sentiment-pipeline.md §10). Implements the same SourceFetcher
protocol as the social fetchers so it plugs into app.intel.scraper.ingest. Best-effort: a non-200
for a symbol is skipped (never raised). parse_company_news is pure for offline testing."""
from datetime import datetime, timedelta, timezone

import httpx

from app.intel.models import RawIntel

_BASE = "https://finnhub.io/api/v1/company-news"
_PER_RUN = 20       # top-N tracked tickers per cycle (rate budget)
_LOOKBACK_DAYS = 7  # company-news window: [today-7d, today]


def parse_company_news(data: list[dict], symbol: str) -> list[RawIntel]:
    """Map Finnhub company-news items to RawIntel. Skips items with no headline."""
    out: list[RawIntel] = []
    for item in data or []:
        headline = (item.get("headline") or "").strip()
        if not headline:
            continue
        summary = (item.get("summary") or "").strip()
        text = (headline + ". " + summary).strip()
        out.append(RawIntel(
            source="finnhub",
            author_handle=(item.get("source") or "finnhub"),
            url=item.get("url"),
            text=text,
            posted_at=datetime.fromtimestamp(item.get("datetime") or 0, tz=timezone.utc),
            symbols=[symbol]))
    return out


class FinnhubNewsFetcher:
    name = "finnhub"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def fetch(self, symbols: list[str]) -> list[RawIntel]:
        if not self.enabled:
            return []
        today = datetime.now(timezone.utc).date()
        frm = (today - timedelta(days=_LOOKBACK_DAYS)).isoformat()
        to = today.isoformat()
        out: list[RawIntel] = []
        async with httpx.AsyncClient(timeout=20) as c:
            for sym in symbols[:_PER_RUN]:
                try:
                    r = await c.get(_BASE, params={
                        "symbol": sym, "from": frm, "to": to, "token": self.api_key})
                    if r.status_code == 200:
                        out.extend(parse_company_news(r.json(), sym))
                except Exception:  # noqa: BLE001 - best-effort per symbol, never abort the run
                    continue
        return out
