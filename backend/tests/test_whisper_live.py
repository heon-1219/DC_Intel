"""Live-refresh checks for the AIWCE fetchers (excluded from the default run; hit real free APIs).
They confirm the recorded cassettes still match the live contract, so a silent upstream shape change
is caught on demand. Run: pytest backend/tests/test_whisper_live.py -m live

NOTE on REAL data (owner standard #4): the offline parse tests run against verbatim recorded
cassettes; these live tests are the refresh path. We assert SHAPE/plausibility, not exact values
(whisper numbers drift between quarters), so a passing live test never depends on fabricated data."""
from datetime import date

import pytest

from app.intel.whisper.fetchers.earningswhispers_fetcher import EarningsWhispersFetcher
from app.intel.whisper.fetchers.stocktwits_fetcher import StockTwitsWhisperFetcher
from app.intel.whisper.fetchers.websearch_fetcher import WhisperNumberFetcher
from app.intel import whisper_config as cfg


@pytest.mark.live
def test_live_earningswhispers_returns_plausible_obs():
    # NVDA reliably exists on earningswhispers; the endpoint returns the most-recent quarter.
    obs = EarningsWhispersFetcher(ticker="NVDA").fetch("earningswhispers")
    if not obs:                                   # fail-open: a transient block is not a hard fail
        pytest.skip("earningswhispers unreachable from this host right now")
    o = obs[0]
    assert o.source == "earningswhispers"
    assert o.value is not None and abs(o.value) <= cfg.PLAUSIBLE_ABS_CAP
    assert isinstance(o.as_of_date, date)


@pytest.mark.live
def test_live_whispernumber_returns_plausible_obs():
    obs = WhisperNumberFetcher(ticker="AAPL", as_of=date.today()).fetch("websearch")
    if not obs:
        pytest.skip("thewhispernumber unreachable from this host right now")
    o = obs[0]
    assert o.source == "websearch"
    assert o.value is not None and abs(o.value) <= cfg.PLAUSIBLE_ABS_CAP


@pytest.mark.live
def test_live_stocktwits_extractor_is_noise_safe():
    # Tier D is noise-only: any candidate it does surface must be EPS-plausible, never a price target.
    obs = StockTwitsWhisperFetcher(ticker="AVGO", as_of=date.today()).fetch("stocktwits")
    for o in obs:
        assert abs(o.value) <= cfg.PLAUSIBLE_ABS_CAP


@pytest.mark.live
def test_live_estimize_blocked_documented():
    # Estimize EPS values are WAF-gated (HTTP 202 x-amzn-waf-action: challenge) from datacenter IPs;
    # no FREE/local-first path exists, so the fetcher stays disabled and emits nothing. This test
    # documents that contract rather than fabricating a cassette (owner standard #4).
    from app.intel.whisper.fetchers.estimize_fetcher import EstimizeFetcher
    f = EstimizeFetcher(ticker="NKE")
    assert f.enabled is False
    assert f.fetch("estimize") == []
