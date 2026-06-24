import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import whisper as wrepo
from app.intel.whisper.models import WhisperObservation
from app.jobs.whisper_corroborator import parse_earnings_anchor, resolve_prior, run_whisper_corroborator
from app.intel import whisper_config as cfg

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
NOW = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)


# ---- pure parse helper (anchor extraction from a stored earnings event row) ----

def test_parse_earnings_anchor_extracts_symbol_eps_date():
    row = {
        "event_type": "earnings:NVDA:NASDAQ",
        "event_time": "2026-07-01T21:00:00Z",
        "actual_vs_forecast_json": json.dumps(
            {"metrics": [{"key": "eps", "forecast": 1.70, "actual": None, "primary": True}]}),
    }
    a = parse_earnings_anchor(row)
    assert a is not None
    assert a["symbol"] == "NVDA" and a["exchange"] == "NASDAQ"
    assert a["consensus_eps"] == 1.70
    assert a["earnings_date"] == date(2026, 7, 1)


def test_parse_earnings_anchor_none_when_not_earnings():
    assert parse_earnings_anchor({"event_type": "us_cpi", "event_time": "2026-07-01T12:30:00Z",
                                  "actual_vs_forecast_json": None}) is None


def test_parse_earnings_anchor_keeps_row_when_consensus_missing():
    # No consensus EPS yet -> anchor None, but symbol/date still resolved so the engine can
    # abstain with NO_ANCHOR (honest) rather than silently skipping the stock.
    row = {"event_type": "earnings:AAPL:NASDAQ", "event_time": "2026-07-30T21:00:00Z",
           "actual_vs_forecast_json": None}
    a = parse_earnings_anchor(row)
    assert a["symbol"] == "AAPL" and a["consensus_eps"] is None
    assert a["earnings_date"] == date(2026, 7, 30)


# ---- the scheduled job (engine wired to a FakeFetcher, persisted via the repo) ----

class FakeFetcher:
    """Replays canned observations per source (the engine's existing injected-fetcher contract)."""
    def __init__(self, by_source):
        self.by_source = by_source

    def fetch(self, source):
        return list(self.by_source.get(source, []))


def _make_fetcher_factory(by_source):
    def factory(symbol, exchange, earnings_date):
        return FakeFetcher(by_source)
    return factory


def _o(value, source, as_of):
    return WhisperObservation(
        value=value, raw_value=str(value), source=source, source_family=cfg.source_family(source),
        source_credibility_prior=cfg.source_prior(source), as_of_date=as_of, context_snippet=source)


async def _db_with_earnings(tmp_path, *, with_consensus=True):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    avf = (json.dumps({"metrics": [{"key": "eps", "forecast": 1.70, "primary": True}]})
           if with_consensus else None)
    async with connect(db) as con:
        await con.execute(
            "INSERT INTO stocks (symbol, exchange, region, company_name, yfinance_ticker) "
            "VALUES ('NVDA','NASDAQ','US','NVIDIA Corp','NVDA')")
        await con.execute(
            "INSERT INTO economic_events (event_name, event_time, impact_level, "
            "actual_vs_forecast_json, provider, provider_event_id, event_type, country, status) "
            "VALUES ('NVDA Earnings', '2026-07-01T21:00:00Z', 'high', ?, 'finnhub', "
            "'earnings:NVDA:2026-07-01', 'earnings:NVDA:NASDAQ', 'US', 'scheduled')", (avf,))
        await con.commit()
    return db


@pytest.mark.asyncio
async def test_job_persists_corroborated_result(tmp_path):
    db = await _db_with_earnings(tmp_path)
    d = date(2026, 6, 23)   # the day before today — fresh whispers, just below the report
    # three distinct families agreeing tightly + close to the 1.70 anchor -> clears the 75 floor.
    fetcher_factory = _make_fetcher_factory({
        "earningswhispers": [_o(1.72, "earningswhispers", d)],
        "estimize": [_o(1.72, "estimize", d)],
        "websearch": [_o(1.72, "websearch", d)],
    })
    n = await run_whisper_corroborator(db, fetcher_factory=fetcher_factory, now=NOW)
    assert n == 1
    async with connect(db) as con:
        row = await wrepo.get_latest_for_stock(con, 1)
    assert row["status"] == "corroborated"
    assert row["whisper_value"] == 1.72
    assert row["anchor"] == 1.70
    assert row["abstain_reason"] is None
    assert row["earnings_date"] == "2026-07-01"


@pytest.mark.asyncio
async def test_job_abstains_no_observations_when_fetchers_empty(tmp_path):
    db = await _db_with_earnings(tmp_path)
    n = await run_whisper_corroborator(db, fetcher_factory=_make_fetcher_factory({}), now=NOW)
    assert n == 1                                # one event processed (abstention IS a result)
    async with connect(db) as con:
        row = await wrepo.get_latest_for_stock(con, 1)
    assert row["status"] == "no_reliable_whisper"
    assert row["abstain_reason"] == "NO_OBSERVATIONS"
    assert row["whisper_value"] is None


@pytest.mark.asyncio
async def test_job_abstains_no_anchor_when_consensus_missing(tmp_path):
    db = await _db_with_earnings(tmp_path, with_consensus=False)
    d = date(2026, 6, 30)
    fetcher_factory = _make_fetcher_factory({"earningswhispers": [_o(1.78, "earningswhispers", d)]})
    n = await run_whisper_corroborator(db, fetcher_factory=fetcher_factory, now=NOW)
    assert n == 1
    async with connect(db) as con:
        row = await wrepo.get_latest_for_stock(con, 1)
    assert row["status"] == "no_reliable_whisper"
    assert row["abstain_reason"] == "NO_ANCHOR"


# ---- anchor fallback: a finnhub-less stock recovers a prior from a source's own consensus_eps ----

def _oc(value, source, as_of, consensus):
    """An observation that ALSO carries the source's reported consensus (earningswhispers 'estimate',
    thewhispernumber 'consensus')."""
    return WhisperObservation(
        value=value, raw_value=str(value), source=source, source_family=cfg.source_family(source),
        source_credibility_prior=cfg.source_prior(source), as_of_date=as_of,
        context_snippet=source, consensus_eps=consensus)


def test_resolve_prior_prefers_finnhub_consensus():
    # finnhub has the consensus -> use it directly, tagged 'finnhub' (no fallback fetch).
    prior = resolve_prior(FakeFetcher({}), 1.70, date(2026, 7, 1))
    assert prior is not None and prior.mu0 == 1.70 and prior.consensus_source == "finnhub"


def test_resolve_prior_falls_back_to_source_consensus_when_finnhub_missing():
    fetcher = FakeFetcher({"earningswhispers": [_oc(1.78, "earningswhispers", date(2026, 6, 23), 1.70)]})
    prior = resolve_prior(fetcher, None, date(2026, 7, 1))
    assert prior is not None and prior.mu0 == 1.70 and prior.consensus_source == "earningswhispers"


def test_resolve_prior_none_when_no_source_carries_consensus():
    # finnhub missing AND no source reports a consensus -> still None (engine abstains NO_ANCHOR).
    fetcher = FakeFetcher({"earningswhispers": [_o(1.78, "earningswhispers", date(2026, 6, 23))]})
    assert resolve_prior(fetcher, None, date(2026, 7, 1)) is None


@pytest.mark.asyncio
async def test_job_recovers_anchor_from_source_when_finnhub_lacks_consensus(tmp_path):
    # finnhub event has NO eps forecast, but the sources report a whisper AND their consensus:
    # the job recovers the anchor and corroborates instead of abstaining NO_ANCHOR.
    db = await _db_with_earnings(tmp_path, with_consensus=False)
    d = date(2026, 6, 23)
    fetcher_factory = _make_fetcher_factory({
        "earningswhispers": [_oc(1.72, "earningswhispers", d, 1.70)],
        "estimize": [_oc(1.72, "estimize", d, 1.70)],
        "websearch": [_oc(1.72, "websearch", d, 1.70)],
    })
    n = await run_whisper_corroborator(db, fetcher_factory=fetcher_factory, now=NOW)
    assert n == 1
    async with connect(db) as con:
        row = await wrepo.get_latest_for_stock(con, 1)
    assert row["abstain_reason"] != "NO_ANCHOR"
    assert row["anchor"] == 1.70            # recovered from earningswhispers' reported consensus
    assert row["status"] == "corroborated"
    assert row["whisper_value"] == 1.72


@pytest.mark.asyncio
async def test_job_skips_past_and_far_future_earnings(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    avf = json.dumps({"metrics": [{"key": "eps", "forecast": 1.70, "primary": True}]})
    async with connect(db) as con:
        await con.execute(
            "INSERT INTO stocks (symbol, exchange, region, company_name, yfinance_ticker) "
            "VALUES ('NVDA','NASDAQ','US','NVIDIA Corp','NVDA')")
        # already reported (past) — must NOT be processed
        await con.execute(
            "INSERT INTO economic_events (event_name, event_time, impact_level, "
            "actual_vs_forecast_json, provider, provider_event_id, event_type, country, status) "
            "VALUES ('NVDA Earnings','2026-05-01T21:00:00Z','high',?, 'finnhub', "
            "'earnings:NVDA:2026-05-01','earnings:NVDA:NASDAQ','US','scheduled')", (avf,))
        await con.commit()
    n = await run_whisper_corroborator(db, fetcher_factory=_make_fetcher_factory({}), now=NOW)
    assert n == 0
    async with connect(db) as con:
        assert await wrepo.get_latest_for_stock(con, 1) is None
