"""AIWCE whisper-corroborator job (whisper-corroboration-engine.md §Pipeline). For every stock with
an UPCOMING earnings event inside the lookahead window, build the consensus-EPS anchor from the
event's actual_vs_forecast_json, run the deterministic corroboration engine over the injected free
fetchers, and persist the result OR a first-class abstention via the whisper repo. Reruns daily
(denser near the date); upserts in place per (stock, report date).

The earnings anchor lives on the economic_events row written by the M3 calendar sync:
  event_type = 'earnings:{SYMBOL}:{EXCHANGE}'  and  metrics[key=='eps'].forecast = consensus EPS.
A missing consensus or earnings date is NOT a failure — the engine abstains (NO_ANCHOR /
NO_EARNINGS_DATE), which we store honestly. Fetch errors are swallowed by the engine (fail-open).

Run once: python -m app.jobs.whisper_corroborator [--db PATH]."""
import argparse
import asyncio
import json
from datetime import date, datetime, timedelta, timezone

from app.cache import redis as cache_redis  # noqa: F401 - kept for parity with sibling jobs / future cache busts
from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import economic_events as erepo
from app.db.repositories import stocks as srepo
from app.intel import whisper_config as cfg
from app.intel.whisper.engine import corroborate
from app.intel.whisper.fetchers import build_default_fetcher
from app.intel.whisper.weight import build_prior


def parse_earnings_anchor(row: dict) -> dict | None:
    """Pure: pull (symbol, exchange, consensus_eps, earnings_date) from a stored earnings event row.
    Returns None for non-earnings events. consensus_eps may be None (no estimate yet) — the caller
    keeps the row so the engine can abstain NO_ANCHOR rather than silently dropping the stock."""
    etype = row.get("event_type") or ""
    if not etype.startswith("earnings:"):
        return None
    parts = etype.split(":")
    symbol = parts[1] if len(parts) > 1 else None
    exchange = parts[2] if len(parts) > 2 else "NASDAQ"
    if not symbol:
        return None

    consensus_eps = None
    avf_raw = row.get("actual_vs_forecast_json")
    if avf_raw:
        try:
            avf = json.loads(avf_raw)
            metrics = avf.get("metrics") or []
            eps_metric = next((m for m in metrics if m.get("key") == "eps"), None)
            if eps_metric is not None and eps_metric.get("forecast") is not None:
                consensus_eps = float(eps_metric["forecast"])
        except (ValueError, TypeError, KeyError):
            consensus_eps = None

    try:
        earnings_date = datetime.fromisoformat(
            row["event_time"].replace("Z", "+00:00")).astimezone(timezone.utc).date()
    except (ValueError, KeyError, AttributeError):
        return None

    return {"symbol": symbol, "exchange": exchange, "consensus_eps": consensus_eps,
            "earnings_date": earnings_date}


def _default_fetcher_factory(symbol: str, exchange: str, earnings_date: date):
    return build_default_fetcher(symbol, exchange, earnings_date)


async def run_whisper_corroborator(db_path: str, *, fetcher_factory=None, now=None) -> int:
    """Process every upcoming-earnings stock. `fetcher_factory(symbol, exchange, earnings_date)`
    returns an object with `.fetch(source) -> list[WhisperObservation]` (real scrapers in prod, a
    FakeFetcher in tests). Returns the count of events for which a row (result or abstention) was
    written."""
    fetcher_factory = fetcher_factory or _default_fetcher_factory
    now_dt = now if isinstance(now, datetime) else (
        datetime.fromisoformat(now.replace("Z", "+00:00")) if now else datetime.now(timezone.utc))
    now_dt = now_dt.astimezone(timezone.utc)
    today = now_dt.date()
    from_utc = now_dt.isoformat().replace("+00:00", "Z")
    to_utc = (now_dt + timedelta(days=cfg.LOOKAHEAD_DAYS)).isoformat().replace("+00:00", "Z")

    from app.db.repositories import whisper as wrepo  # local import: keeps the module import-light

    processed = 0
    async with connect(db_path) as con:
        rows = await erepo.list_in_range(con, from_utc, to_utc, impact=["high", "medium"])
        for row in rows:
            anchor = parse_earnings_anchor(row)
            if anchor is None:
                continue
            ref = await srepo.get_stock(con, anchor["symbol"], anchor["exchange"])
            if ref is None:
                continue
            prior = build_prior(anchor["consensus_eps"], anchor["earnings_date"])
            fetcher = fetcher_factory(anchor["symbol"], anchor["exchange"], anchor["earnings_date"])
            result = corroborate(prior, fetcher, today=today, computed_at=now_dt)
            await wrepo.upsert_result(con, stock_id=ref.id, earnings_event_id=row.get("id"),
                                      earnings_date=anchor["earnings_date"], result=result)
            processed += 1
    return processed


def _main(argv=None):
    p = argparse.ArgumentParser(description="Corroborate whisper EPS for upcoming-earnings stocks.")
    p.add_argument("--db", default=get_settings().sqlite_path)
    a = p.parse_args(argv)
    n = asyncio.run(run_whisper_corroborator(a.db))
    print(f"processed {n}")


if __name__ == "__main__":
    _main()
