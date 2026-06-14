import asyncio
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.providers.base import StockRef
from app.providers.retry import ProviderError

# Calendar-day lookback per interval (§3.1; respects yfinance 5m/15m<=60d, 1h<=730d).
_DAYS = {"5m": 14, "15m": 35, "1h": 130, "1d": 1100}
INTERVAL_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
_COLS = ["open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame, interval: str, now: datetime) -> pd.DataFrame:
    """Lowercase+select OHLCV, force a UTC index, drop NaN-close rows, and drop the
    currently-forming trailing bar (its interval hasn't closed yet). §8 / §8.3."""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=_COLS)
    df = df.rename(columns=str.lower)
    df = df[[c for c in _COLS if c in df.columns]].copy()
    df.index = pd.to_datetime(df.index, utc=True)   # tz-aware -> UTC; naive -> UTC
    df = df.dropna(subset=["close"])
    if len(df):
        last = df.index[-1].to_pydatetime()
        if last + timedelta(seconds=INTERVAL_SECONDS[interval]) > now:
            df = df.iloc[:-1]
    return df


class YFinanceBarProvider:
    name = "yfinance_bars"

    async def fetch_bars(self, ref: StockRef, interval: str) -> pd.DataFrame:
        now = datetime.now(timezone.utc)
        try:
            return await asyncio.to_thread(
                self._fetch, ref.yfinance_ticker, interval, _DAYS[interval], now)
        except Exception as e:  # noqa: BLE001 - normalize everything to retryable
            raise ProviderError(f"yfinance_bars {ref.yfinance_ticker} {interval}: {e}") from e

    @staticmethod
    def _fetch(ticker: str, interval: str, days: int, now: datetime) -> pd.DataFrame:
        import yfinance as yf  # lazy: heavy import; keeps the offline suite fast

        start = (now - timedelta(days=days)).date().isoformat()
        end = (now + timedelta(days=1)).date().isoformat()
        raw = yf.Ticker(ticker).history(
            start=start, end=end, interval=interval, prepost=False, auto_adjust=True)
        return _normalize(raw, interval, now)
