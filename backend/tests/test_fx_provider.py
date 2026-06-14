import pytest

from app.providers.fx_provider import FxProvider
from app.providers.retry import ProviderError


@pytest.mark.asyncio
async def test_fx_wraps_errors(monkeypatch):
    import app.providers.fx_provider as mod

    def boom():
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(mod.FxProvider, "_fetch", staticmethod(boom))
    with pytest.raises(ProviderError):
        await FxProvider().fetch_usdkrw()


@pytest.mark.live
@pytest.mark.asyncio
async def test_fx_live():
    rate = await FxProvider().fetch_usdkrw()
    assert rate > 500  # USDKRW is ~1000-1500
