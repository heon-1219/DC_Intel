from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class StockRef:
    id: int
    symbol: str
    exchange: str
    region: str
    currency: str
    yfinance_ticker: str
    finnhub_ticker: str | None
    company_name: str | None = None       # trailing/defaulted: positional construction unaffected
    company_name_ko: str | None = None


@dataclass(frozen=True)
class PriceQuote:
    price: float
    previous_close: float | None
    volume: int | None
    day_high: float | None
    day_low: float | None
    as_of: datetime  # timezone-aware UTC


class Provider(Protocol):
    name: str
    async def fetch_quote(self, ref: StockRef) -> PriceQuote: ...
