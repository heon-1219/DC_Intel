from app.providers.base import PriceQuote, StockRef


class FakeProvider:
    def __init__(self, name: str, quote: PriceQuote | None = None, error: Exception | None = None):
        self.name = name
        self._quote = quote
        self._error = error
        self.calls = 0

    async def fetch_quote(self, ref: StockRef) -> PriceQuote:
        self.calls += 1
        if self._error is not None:
            raise self._error
        assert self._quote is not None
        return self._quote


class FakeBarProvider:
    def __init__(self, name="yfinance_bars", bars=None, error: Exception | None = None):
        self.name = name
        self._bars = bars        # a pandas DataFrame, or a dict interval -> DataFrame
        self._error = error
        self.calls = 0

    async def fetch_bars(self, ref, interval):
        self.calls += 1
        if self._error is not None:
            raise self._error
        if isinstance(self._bars, dict):
            return self._bars[interval]
        return self._bars


class FakeCalendarProvider:
    def __init__(self, name: str, events=None, error: Exception | None = None):
        self.name = name
        self._events = events or []
        self._error = error
        self.calls = 0

    async def fetch_scheduled(self, start_utc, end_utc):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return list(self._events)
