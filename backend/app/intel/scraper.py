"""intel_scraper ingest orchestrator (market-intel-pipeline.md §3). Runs each enabled fetcher,
then per item: clean → extract entities → resolve stock_id → exact-dedup → insert into
market_intel. Embedding/clustering/credibility/sentiment are applied by later slices (M4b/M4c).
Resilient: a failing source is skipped, never aborts the run."""
from datetime import datetime, timezone

from app.db.connection import connect
from app.db.repositories import market_intel as mi_repo
from app.db.repositories import stocks as srepo
from app.intel.dedup import is_exact_duplicate
from app.intel.entities import extract_cashtags, resolve_symbol
from app.intel.normalize import clean_snippet


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def ingest(db_path: str, redis, fetchers, *, now: datetime | None = None) -> int:
    """Returns the number of new market_intel rows inserted (after exact-dedup)."""
    async with connect(db_path) as con:
        stocks = await srepo.list_active_all(con)
    by_symbol = {s.symbol.upper(): s.id for s in stocks}
    by_name_ko = {s.company_name_ko: s.id for s in stocks if s.company_name_ko}
    tracked = [s.symbol for s in stocks]

    inserted = 0
    for f in fetchers:
        if not getattr(f, "enabled", True):
            continue
        try:
            raws = await f.fetch(tracked)
        except Exception:  # noqa: BLE001 - a source must never abort the whole run
            continue
        for raw in raws:
            if await is_exact_duplicate(redis, raw.text):
                continue
            syms = raw.symbols or extract_cashtags(raw.text)
            stock_id = None
            for sym in syms:
                key = sym.upper() if sym.isascii() else sym
                stock_id = resolve_symbol(key, by_symbol, by_name_ko)
                if stock_id:
                    break
            async with connect(db_path) as con:
                await mi_repo.insert_intel(
                    con, source=raw.source, author_handle=raw.author_handle,
                    content_snippet=clean_snippet(raw.text), posted_at=_iso(raw.posted_at),
                    stock_id=stock_id, url=raw.url)
            inserted += 1
    return inserted
