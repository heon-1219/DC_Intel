import httpx
import pytest
import respx

from app.providers.base import StockRef
from app.providers.finnhub_provider import FinnhubProvider
from app.providers.retry import ProviderError

REF = StockRef(5, "AAPL", "NASDAQ", "US", "USD", "AAPL", "AAPL")


@pytest.mark.asyncio
@respx.mock
async def test_finnhub_quote_maps_fields():
    # Real Finnhub /quote shape: c=current, pc=prev close, h=high, l=low, t=epoch.
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 201.5, "pc": 199.0, "h": 203.0,
                                               "l": 198.4, "t": 1749700000}))
    q = await FinnhubProvider(api_key="k").fetch_quote(REF)
    assert q.price == 201.5
    assert q.previous_close == 199.0
    assert q.day_high == 203.0 and q.day_low == 198.4


@pytest.mark.asyncio
@respx.mock
async def test_finnhub_5xx_raises_providererror():
    respx.get("https://finnhub.io/api/v1/quote").mock(return_value=httpx.Response(503))
    with pytest.raises(ProviderError):
        await FinnhubProvider(api_key="k").fetch_quote(REF)


@pytest.mark.asyncio
@respx.mock
async def test_finnhub_empty_quote_raises_providererror():
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 0}))
    with pytest.raises(ProviderError):
        await FinnhubProvider(api_key="k").fetch_quote(REF)
