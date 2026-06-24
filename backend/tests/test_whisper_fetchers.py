"""Parse tests for the AIWCE source fetchers, run against REAL recorded cassettes (owner standard #4:
fixtures are recorded from real APIs, never fabricated). The cassettes were captured verbatim during
recon and verified byte-identical to a live re-fetch."""
import json
from datetime import date
from pathlib import Path

from app.intel import whisper_config as cfg
from app.intel.whisper.fetchers.earningswhispers_fetcher import (EarningsWhispersFetcher,
                                                                 parse_earningswhispers)
from app.intel.whisper.fetchers.stocktwits_fetcher import (StockTwitsWhisperFetcher,
                                                           parse_stocktwits_whisper)
from app.intel.whisper.fetchers.websearch_fetcher import (WhisperNumberFetcher,
                                                          parse_whispernumber)

CASS = Path(__file__).resolve().parent / "cassettes"


# ---------------- Tier A: earningswhispers (clean JSON) ----------------

def test_parse_earningswhispers_extracts_whisper_estimate_date():
    raw = json.loads((CASS / "whisper_earningswhispers.json").read_text())
    obs = parse_earningswhispers(raw)
    assert len(obs) == 1
    o = obs[0]
    assert o.source == "earningswhispers"
    assert o.source_family == "earningswhispers"
    assert o.value == 1.78                          # the 'whisper' field, verbatim
    assert o.consensus_eps == 1.70                  # 'estimate' -> anchor candidate
    assert o.as_of_date == date(2026, 5, 20)        # from epsDate ISO datetime
    assert o.quarter and "April 2026" in o.quarter
    assert o.source_credibility_prior == cfg.source_prior("earningswhispers")


def test_parse_earningswhispers_treats_sentinel_as_null_and_missing_whisper():
    # -999.0 sentinel (seen in ewGrade/pwrRating) must not leak in; a missing whisper -> no obs.
    raw = {"ticker": "FOO", "whisper": -999.0, "estimate": 1.20, "epsDate": "2026-07-01T16:20:00"}
    assert parse_earningswhispers(raw) == []
    assert parse_earningswhispers({"ticker": "BAR", "estimate": 1.0,
                                   "epsDate": "2026-07-01T16:20:00"}) == []


def test_earningswhispers_fetcher_is_enabled_keyless():
    f = EarningsWhispersFetcher()
    assert f.name == "earningswhispers" and f.enabled is True


# ---------------- Tier C: websearch -> thewhispernumber.com (clean HTML) ----------------

def test_parse_whispernumber_from_meta_description():
    html = (CASS / "whisper_websearch.html").read_text()
    obs = parse_whispernumber(html, as_of=date(2026, 6, 24))
    assert len(obs) == 1
    o = obs[0]
    assert o.source == "websearch" and o.source_family == "websearch"
    assert o.value == 1.99                          # whisper number from the <meta> headline
    assert o.consensus_eps == 1.89                  # consensus from the same headline
    assert o.as_of_date == date(2026, 6, 24)        # websearch obs are dated "today"
    assert "Jul 30, 2026" in (o.context_snippet or "")


def test_parse_whispernumber_empty_when_no_meta():
    assert parse_whispernumber("<html><head></head><body>no data</body></html>",
                               as_of=date(2026, 6, 24)) == []


def test_whispernumber_fetcher_is_enabled_keyless():
    f = WhisperNumberFetcher()
    assert f.name == "websearch" and f.enabled is True


# ---------------- Tier D: stocktwits (noisy free text — extraction + noise rejection) ----------------

def test_parse_stocktwits_whisper_rejects_price_and_option_noise():
    # The real AVGO cassette holds only price/option chatter (no EPS whisper). The Tier-D extractor
    # must therefore yield ZERO clean EPS candidates here — its job is to be silent on noise, not to
    # hallucinate an EPS from a $450 price target. (Per recon: stocktwits is noise-only corroboration.)
    raw = json.loads((CASS / "whisper_stocktwits.json").read_text())
    obs = parse_stocktwits_whisper(raw, as_of=date(2026, 6, 24))
    for o in obs:
        # any candidate that DID parse must be in a plausible quarterly-EPS magnitude, never a price.
        assert abs(o.value) <= cfg.PLAUSIBLE_ABS_CAP
        assert o.source == "stocktwits" and o.source_family == "forum"


def test_parse_stocktwits_whisper_extracts_explicit_eps_mention():
    # A synthetic-SHAPE message exercising the extractor (NOT a fabricated cassette): when a body
    # explicitly says "EPS whisper $1.95", the extractor should surface it.
    data = {"messages": [
        {"id": 1, "body": "$AVGO EPS whisper 1.95 this quarter", "created_at": "2026-06-24T10:00:00Z",
         "user": {"username": "u1"}},
        {"id": 2, "body": "$AVGO Call Wall: $390.00 Put Wall: $380.00", "created_at": "2026-06-24T10:01:00Z",
         "user": {"username": "u2"}},
    ]}
    obs = parse_stocktwits_whisper(data, as_of=date(2026, 6, 24))
    vals = [o.value for o in obs]
    assert 1.95 in vals
    assert 390.0 not in vals and 380.0 not in vals   # price-target noise rejected by the cap


def test_stocktwits_whisper_fetcher_is_enabled_keyless():
    f = StockTwitsWhisperFetcher()
    assert f.name == "stocktwits" and f.enabled is True
