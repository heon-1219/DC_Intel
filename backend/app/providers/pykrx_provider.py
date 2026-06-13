import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.providers.base import PriceQuote, StockRef
from app.providers.retry import ProviderError

_KST = ZoneInfo("Asia/Seoul")


class PykrxProvider:
    name = "pykrx"

    async def fetch_quote(self, ref: StockRef) -> PriceQuote:
        try:
            return await asyncio.to_thread(self._fetch, ref.symbol)
        except Exception as e:  # noqa: BLE001 - normalize to retryable
            raise ProviderError(f"pykrx {ref.symbol}: {e}") from e

    @staticmethod
    def _fetch(symbol: str) -> PriceQuote:
        from pykrx import stock as krx  # lazy: pykrx pulls pandas; keeps the offline suite fast

        now_kst = datetime.now(timezone.utc).astimezone(_KST)
        end = now_kst.strftime("%Y%m%d")
        start = (now_kst - timedelta(days=10)).strftime("%Y%m%d")  # window survives weekends/holidays
        df = krx.get_market_ohlcv(start, end, symbol)  # cols: 시가/고가/저가/종가/거래량, index=date
        if df is None or df.empty:
            raise ValueError("no ohlcv in window")
        row = df.iloc[-1]
        prev_close = float(df.iloc[-2]["종가"]) if len(df) >= 2 else None
        bar_date = df.index[-1]
        as_of = datetime(bar_date.year, bar_date.month, bar_date.day, 15, 30, tzinfo=_KST).astimezone(timezone.utc)
        return PriceQuote(
            price=float(row["종가"]),
            previous_close=prev_close,
            volume=int(row["거래량"]),
            day_high=float(row["고가"]),
            day_low=float(row["저가"]),
            as_of=as_of,
        )
