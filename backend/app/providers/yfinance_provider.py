import asyncio
from datetime import datetime, timezone

from app.providers.base import PriceQuote, StockRef
from app.providers.retry import ProviderError


def _f(v):
    return None if v is None else float(v)


def _i(v):
    return None if v is None else int(v)


class YFinanceProvider:
    name = "yfinance"

    async def fetch_quote(self, ref: StockRef) -> PriceQuote:
        try:
            return await asyncio.to_thread(self._fetch, ref.yfinance_ticker)
        except Exception as e:  # noqa: BLE001 - normalize everything to retryable
            raise ProviderError(f"yfinance {ref.yfinance_ticker}: {e}") from e

    @staticmethod
    def _fetch(ticker: str) -> PriceQuote:
        import yfinance as yf  # lazy: yfinance import is heavy; keeps the offline suite fast

        fi = yf.Ticker(ticker).fast_info  # FastInfo: stable attribute interface
        price = getattr(fi, "last_price", None)
        if price is None:
            raise ValueError("no last_price")
        return PriceQuote(
            price=float(price),
            previous_close=_f(getattr(fi, "previous_close", None)),
            volume=_i(getattr(fi, "last_volume", None)),
            day_high=_f(getattr(fi, "day_high", None)),
            day_low=_f(getattr(fi, "day_low", None)),
            as_of=datetime.now(timezone.utc),
        )
