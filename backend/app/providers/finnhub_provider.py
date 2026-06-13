from datetime import datetime, timezone

import httpx

from app.providers.base import PriceQuote, StockRef
from app.providers.retry import ProviderError

_BASE = "https://finnhub.io/api/v1/quote"


class FinnhubProvider:
    name = "finnhub"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_quote(self, ref: StockRef) -> PriceQuote:
        symbol = ref.finnhub_ticker or ref.symbol
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(_BASE, params={"symbol": symbol, "token": self.api_key})
            if resp.status_code == 429 or resp.status_code >= 500:
                raise ProviderError(f"finnhub http {resp.status_code}")
            resp.raise_for_status()
            d = resp.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"finnhub {symbol}: {e}") from e
        if not d.get("c"):
            raise ProviderError(f"finnhub {symbol}: empty quote")
        ts = d.get("t")
        return PriceQuote(
            price=float(d["c"]),
            previous_close=float(d["pc"]) if d.get("pc") else None,
            volume=None,  # /quote carries no volume; left null in v1
            day_high=float(d["h"]) if d.get("h") else None,
            day_low=float(d["l"]) if d.get("l") else None,
            as_of=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc),
        )
