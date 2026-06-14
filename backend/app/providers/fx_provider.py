import asyncio

from app.providers.retry import ProviderError


class FxProvider:
    name = "fx"

    async def fetch_usdkrw(self) -> float:
        try:
            return await asyncio.to_thread(self._fetch)
        except Exception as e:  # noqa: BLE001 - normalize to retryable
            raise ProviderError(f"fx USDKRW: {e}") from e

    @staticmethod
    def _fetch() -> float:
        import yfinance as yf  # lazy: keep offline suite fast

        fi = yf.Ticker("KRW=X").fast_info  # Yahoo KRW=X = KRW per 1 USD
        rate = getattr(fi, "last_price", None)
        if not rate:
            raise ValueError("no fx rate")
        return float(rate)
