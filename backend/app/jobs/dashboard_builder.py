"""Write-through builders for the read-only dashboard blobs (backend-design §5/§6.7/§6.8). A 60s job
assembles dash:indexes + dash:trending:{kr,us,all} from the px:quote:* cache the poll jobs already
wrote, attaching an on-demand intraday sparkline (build_sparkline) and the per-stock win-rate badge
(accuracy_stats). The /dashboard/{indexes,trending} handlers only READ these keys."""
import json
from datetime import datetime, timezone

from app.db.connection import connect
from app.db.repositories import accuracy as accrepo
from app.db.repositories import stocks as srepo
from app.market.hours import index_state, market_state
from app.services import price as svc
from app.services.sparkline import build_sparkline

_TTL = 60          # matches the 60s read cache / poll cadence
_TOP_N = 10        # movers stored per list (endpoint slices to its `limit`, max 20 -> store up to 20)
_STORE_N = 20


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _change_pct(c) -> float | None:
    pc = c.get("previous_close") if c else None
    return round((c["price"] - pc) / pc * 100, 2) if (c and pc) else None


async def build_indexes(db: str, redis, bars, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    async with connect(db) as con:
        refs = await srepo.list_active_indexes(con)
    out = []
    for ref in refs:
        c = await svc.read_cached(redis, ref.symbol, ref.exchange)
        cp = _change_pct(c)
        level = c["price"] if c else None
        out.append({
            "code": ref.symbol,
            "name_en": ref.company_name or ref.symbol,
            "name_ko": ref.company_name_ko or ref.company_name or ref.symbol,
            "level": level,
            "change": round(level - c["previous_close"], 4) if (c and c.get("previous_close")) else None,
            "change_pct": cp,
            "market_state": index_state(ref.region, now),
            "sparkline": await build_sparkline(bars, ref),
            "data_as_of": c["as_of"] if c else None,
        })
    await redis.set("dash:indexes",
                    json.dumps({"indexes": out, "built_at": _iso(now), "source": "yfinance"}), ex=_TTL)
    return out


async def build_trending(db: str, redis, bars, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    async with connect(db) as con:
        kr = await srepo.list_active_by_region(con, "KR")
        us = await srepo.list_active_by_region(con, "US")

    quotes = {}
    for ref in {r.id: r for r in kr + us}.values():
        quotes[ref.id] = await svc.read_cached(redis, ref.symbol, ref.exchange)

    def _rank(refs):
        rows = [(cp, ref, quotes[ref.id]) for ref in refs
                if (cp := _change_pct(quotes.get(ref.id))) is not None]
        gainers = sorted((r for r in rows if r[0] >= 0), key=lambda r: -r[0])[:_STORE_N]
        losers = sorted((r for r in rows if r[0] < 0), key=lambda r: r[0])[:_STORE_N]
        return gainers, losers

    kr_g, kr_l = _rank(kr)
    us_g, us_l = _rank(us)
    needed = {ref.id: ref for cp, ref, c in (kr_g + kr_l + us_g + us_l)}

    spark = {rid: await build_sparkline(bars, ref) for rid, ref in needed.items()}
    win = {}
    if needed:
        async with connect(db) as con:
            for rid in needed:
                s = await accrepo.accuracy_stats(con, rid, window="all", now_iso=_iso(now))
                # win_rate_pct is DIRECTIONAL (neutral counts as a loss), so n_closed must be the
                # directional denominator too — pairing it with graded_total (incl. neutrals) would
                # mislabel the badge. Gate the rate on that same directional count (>= MIN_SAMPLE).
                dp = s["directional"]["predictions"]
                wr = s["directional"]["win_rate_pct"] if dp >= accrepo.MIN_SAMPLE else None
                win[rid] = (wr, dp)

    def _card(cp, ref, c):
        wr, nc = win.get(ref.id, (None, 0))
        return {
            "instrument": f"{ref.symbol}:{ref.exchange}",
            "name_en": ref.company_name or ref.symbol,
            "name_ko": ref.company_name_ko or ref.company_name or ref.symbol,
            "price": c["price"], "currency": c.get("currency", ref.currency),
            "change_pct": cp, "volume": c.get("volume"),
            "sparkline": spark.get(ref.id, []),
            "win_rate_pct": wr, "n_closed": nc,
        }

    kr_obj = {"region": "kr", "market_state": market_state("KRX", now),
              "gainers": [_card(*x) for x in kr_g], "losers": [_card(*x) for x in kr_l]}
    us_obj = {"region": "us", "market_state": market_state("NASDAQ", now),
              "gainers": [_card(*x) for x in us_g], "losers": [_card(*x) for x in us_l]}
    per_region = {"kr": [kr_obj], "us": [us_obj], "all": [kr_obj, us_obj]}
    for region, objs in per_region.items():
        await redis.set(f"dash:trending:{region}",
                        json.dumps({"regions": objs, "built_at": _iso(now), "source": "yfinance"}),
                        ex=_TTL)
    return per_region


async def build_dashboard_blobs(db: str, redis, bars, *, now: datetime | None = None) -> None:
    """The scheduler entry point — assemble both blobs each cycle (after the price polls)."""
    await build_indexes(db, redis, bars, now=now)
    await build_trending(db, redis, bars, now=now)
