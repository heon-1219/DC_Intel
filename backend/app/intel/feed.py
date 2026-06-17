"""Build the market-intel feed response from market_intel rows (market-intel-pipeline.md §12).
Pure: groups rows into clusters (by cluster_id; un-clustered rows are singletons), derives
status/badge/sentiment/credibility per cluster. timeline + lead_time + coordinated_warning need
the cluster Redis metadata written by the (deferred) scraper integration; defaulted here."""
from collections import Counter

from app.intel.credibility import band
from app.intel.normalize import detect_lang

# Badge contract (§8.2): blue confirmed / amber speculation — NEVER green/red (those = sentiment).
_BADGE = {
    ("confirmed", "en"): {"label": "Confirmed", "style": "confirmed",
                          "disclaimer": "Corroborated by an official source."},
    ("confirmed", "ko"): {"label": "확인됨", "style": "confirmed",
                          "disclaimer": "공식 출처로 확인된 정보예요."},
    ("speculation", "en"): {"label": "Unconfirmed — rumor", "style": "speculation",
                            "disclaimer": "Unverified social chatter — treat with caution."},
    ("speculation", "ko"): {"label": "미확인 — 소문", "style": "speculation",
                            "disclaimer": "확인되지 않은 소문이에요 — 주의하세요."},
}


def cluster_sentiment(items: list[dict]) -> tuple[str, float]:
    """Count-weighted majority label among non-neutral items; mean confidence of that label."""
    nonneutral = [it for it in items if it["sentiment"] in ("bullish", "bearish")]
    if not nonneutral:
        return "neutral", 0.0
    label = Counter(it["sentiment"] for it in nonneutral).most_common(1)[0][0]
    confs = [it["sentiment_confidence"] for it in nonneutral if it["sentiment"] == label]
    return label, round(sum(confs) / len(confs), 2)


def _item_view(it: dict) -> dict:
    return {
        "id": it["id"], "source": it["source"], "author_handle": it["author_handle"],
        "url": it["url"], "content_snippet": it["content_snippet"],
        "lang": detect_lang(it["content_snippet"]), "posted_at": it["posted_at"],
        "credibility_score": it["credibility_score"], "sentiment": it["sentiment"],
        "sentiment_confidence": it["sentiment_confidence"], "confirmed": bool(it["confirmed"]),
    }


def build_clusters(rows: list[dict], *, lang: str = "en", min_credibility: int = 25,
                   limit: int = 20) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["cluster_id"] or f"single:{r['id']}", []).append(r)

    out: list[dict] = []
    for key, items in groups.items():
        max_cred = max(it["credibility_score"] for it in items)
        if max_cred < min_credibility:
            continue
        ordered = sorted(items, key=lambda it: it["credibility_score"], reverse=True)
        confirmed = any(it["confirmed"] for it in items)
        style = "confirmed" if confirmed else "speculation"
        coordinated = any(it["credibility_score"] <= 20 for it in items) and len(items) >= 3
        sent, sconf = cluster_sentiment(items)
        out.append({
            "cluster_id": items[0]["cluster_id"] or key,
            "_stock_id": items[0]["stock_id"],          # router maps -> stock object
            "status": "CONFIRMED" if confirmed else "UNCONFIRMED",
            "badge": _BADGE[(style, lang)],
            "sentiment": sent, "sentiment_confidence": sconf,
            "item_count": len(items),
            "distinct_authors": len({(it["source"], it["author_handle"]) for it in items}),
            "max_credibility": max_cred, "credibility_band": band(max_cred),
            "coordinated_warning": coordinated,
            "lead_time_minutes": None,                  # set when an anomaly pins the cluster (M4d)
            "timeline": [],                             # needs cluster Redis meta (deferred)
            "items": [_item_view(it) for it in ordered[:3]],
            "confirm_url": None,
        })
    out.sort(key=lambda c: c["max_credibility"], reverse=True)
    return out[:limit]
