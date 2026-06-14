from datetime import datetime

from app.market.hours import market_state
from app.services import price as svc

_NOTE_EN = ("Prices come from different market sessions; the difference partly reflects "
            "time-zone gaps, not only a premium.")
_NOTE_KO = "거래소마다 장 시간이 달라서, 가격 차이에는 프리미엄뿐 아니라 시차 영향도 섞여 있어요."


def _norm_usd(price, currency: str, adr_ratio, usdkrw) -> float | None:
    """Per-underlying-share USD. KRW via FX; USD as-is; ADR divided by its ratio."""
    if price is None:
        return None
    if currency == "USD":
        usd = price
    elif currency == "KRW":
        if not usdkrw:
            return None
        usd = price / usdkrw
    else:
        return None  # other currencies unsupported in v1
    if adr_ratio:
        usd = usd / adr_ratio
    return usd


async def build_cross_market(base_symbol, base_exchange, names, listings, redis, usdkrw,
                             now: datetime) -> dict:
    base_instrument = f"{base_symbol}:{base_exchange}"
    cache = {}
    base_norm = None
    for lst in listings:
        cached = await svc.read_cached(redis, lst.symbol, lst.exchange)
        price = cached["price"] if cached else None
        norm = _norm_usd(price, lst.currency, lst.adr_ratio, usdkrw)
        cache[lst.instrument] = (cached, norm)
        if lst.instrument == base_instrument:
            base_norm = norm

    rows = []
    for lst in listings:
        cached, norm = cache[lst.instrument]
        state = market_state(lst.exchange, now)
        if cached:
            price = cached["price"]
            pc = cached.get("previous_close")
            change_pct = round((price - pc) / pc * 100, 2) if pc else None
            as_of = cached["as_of"]
            stale = svc.is_stale(datetime.fromisoformat(as_of.replace("Z", "+00:00")), state, now)
        else:
            price = change_pct = as_of = None
            stale = False
        diff = round((norm - base_norm) / base_norm * 100, 2) if (base_norm and norm is not None) else None
        rows.append({
            "instrument": lst.instrument, "exchange": lst.exchange, "currency": lst.currency,
            "price": price, "change_pct": change_pct,
            "adr_ratio": f"1 ADR = {lst.adr_ratio} share" if lst.adr_ratio else None,
            "normalized_usd": round(norm, 2) if norm is not None else None,
            "diff_pct_vs_base": diff, "market_state": state,
            "data_as_of": as_of, "is_stale": stale,
        })

    return {
        "company_name_en": names["en"], "company_name_ko": names["ko"],
        "base_instrument": base_instrument,
        "fx_rates": {"USDKRW": usdkrw, "as_of": now.isoformat().replace("+00:00", "Z")},
        "listings": rows,
        "note_en": _NOTE_EN, "note_ko": _NOTE_KO,
    }
