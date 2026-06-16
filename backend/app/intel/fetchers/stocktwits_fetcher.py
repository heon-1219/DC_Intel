"""StockTwits public stream fetcher (data-sources.md §4.3). Best-effort: the public API now
fronts Cloudflare and may 403 automated/datacenter requests, and a STOCKTWITS_ACCESS_TOKEN
raises the rate limit — so non-200 responses are treated as 'no data' (graceful), never raised."""
from datetime import datetime, timezone

import httpx

from app.intel.models import RawIntel

_BASE = "https://api.stocktwits.com/api/2/streams/symbol"
_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
       "Accept": "application/json"}
_PER_RUN = 20   # top-N tracked tickers per cycle (rate budget)


def _dt(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_stocktwits(data: dict) -> list[RawIntel]:
    out: list[RawIntel] = []
    for m in data.get("messages", []) or []:
        user = m.get("user") or {}
        posted = _dt(m.get("created_at"))
        if posted is None:
            continue
        joined = _dt(user.get("join_date"))
        age_days = (posted - joined).days if joined else None
        sent = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
        weak = {"Bullish": "bullish", "Bearish": "bearish"}.get(sent)
        handle = user.get("username") or "unknown"
        out.append(RawIntel(
            source="stocktwits", author_handle=handle,
            url=f"https://stocktwits.com/{handle}/message/{m.get('id')}",
            text=m.get("body") or "", posted_at=posted,
            symbols=[s.get("symbol") for s in (m.get("symbols") or []) if s.get("symbol")],
            account_age_days=age_days, engagement=user.get("followers"), weak_label=weak))
    return out


class StockTwitsFetcher:
    name = "stocktwits"

    def __init__(self, access_token: str = ""):
        self.access_token = access_token

    @property
    def enabled(self) -> bool:
        return True   # public best-effort; token is optional (raises the rate limit)

    async def fetch(self, symbols: list[str]) -> list[RawIntel]:
        out: list[RawIntel] = []
        params = {"access_token": self.access_token} if self.access_token else None
        async with httpx.AsyncClient(timeout=20, headers=_UA) as c:
            for sym in symbols[:_PER_RUN]:
                try:
                    r = await c.get(f"{_BASE}/{sym}.json", params=params)
                    if r.status_code == 200:
                        out.extend(parse_stocktwits(r.json()))
                except Exception:  # noqa: BLE001 - best-effort per symbol
                    continue
        return out
