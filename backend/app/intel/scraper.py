"""intel_scraper ingest orchestrator (market-intel-pipeline.md §3). Runs each enabled fetcher,
then per item: clean → extract entities → resolve stock_id → exact-dedup → insert. When an
`embedder` is supplied it also embeds the item, assigns it to a cluster (Redis cluster store),
and scores credibility (S/A/C/E) — the full §4–§6 enrichment. With no embedder it just inserts
(M4a behavior). Resilient: a failing source is skipped, never aborts the run."""
import json
from datetime import datetime, timezone

from app.db.connection import connect
from app.db.repositories import market_intel as mi_repo
from app.db.repositories import stocks as srepo
from app.intel import cluster_store
from app.intel.credibility import credibility, subscore_a, subscore_c, subscore_e, subscore_s
from app.intel.dedup import is_exact_duplicate
from app.intel.embed import cache_embedding
from app.intel.entities import extract_cashtags, resolve_symbol
from app.intel.normalize import clean_snippet


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def _author_stats(redis, source: str, handle: str):
    raw = await redis.get(f"intel:authorstats:{source}:{handle}")
    return json.loads(raw) if raw else None


async def ingest(db_path: str, redis, fetchers, *, now: datetime | None = None,
                 embedder=None) -> int:
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
                stock_id = resolve_symbol(sym.upper() if sym.isascii() else sym,
                                          by_symbol, by_name_ko)
                if stock_id:
                    break
            snippet = clean_snippet(raw.text)
            posted = _iso(raw.posted_at)
            async with connect(db_path) as con:
                iid = await mi_repo.insert_intel(
                    con, source=raw.source, author_handle=raw.author_handle,
                    content_snippet=snippet, posted_at=posted, stock_id=stock_id, url=raw.url)
            inserted += 1

            if embedder is None:
                continue
            # Embed → cluster → credibility (§4–§6 enrichment)
            vec = embedder.embed([snippet])[0]
            await cache_embedding(redis, iid, vec)
            cid, distinct, coordinated = await cluster_store.assign(
                redis, stock_id, vec, f"{raw.source}:{raw.author_handle}", posted)
            stats = await _author_stats(redis, raw.source, raw.author_handle)
            cred = credibility(
                subscore_s(raw.source, raw.author_handle),
                subscore_a(stats.get("resolved") if stats else None,
                           stats.get("confirmed") if stats else None),
                subscore_c(distinct),
                subscore_e(raw.account_age_days, raw.engagement),
                coordinated=coordinated)
            async with connect(db_path) as con:
                await mi_repo.set_cluster_and_credibility(con, iid, cid, cred)
    return inserted
