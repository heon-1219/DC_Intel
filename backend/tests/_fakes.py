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
