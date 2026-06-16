"""Per-stock per-timeframe sentiment aggregation (sentiment-pipeline.md §7). Pure: items in,
(headline_score, source_breakdown_json) out. Constants are CODE (cross-doc contract with the
prediction pipeline), NOT env-tunable.

Item: dict {sentiment, confidence, credibility(0-100), posted_at(aware UTC), source,
            market_intel_id, author_handle, url}.
"""
from datetime import datetime, timedelta, timezone


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

# half-life (h), lookback window (h), min item count N — per timeframe (§7.2)
HALF_LIVES = {"1h": 0.5, "5h": 2.0, "24h": 6.0, "2d": 12.0, "3d": 18.0, "5d": 24.0}
LOOKBACKS = {"1h": 2, "5h": 8, "24h": 24, "2d": 48, "3d": 72, "5d": 120}
MIN_N = {"1h": 5, "5h": 8, "24h": 10, "2d": 12, "3d": 12, "5d": 15}
_DIR = {"bullish": 1, "bearish": -1, "neutral": 0}


def item_score(sentiment: str, confidence: float) -> float:
    """s_i = dir · conf · 100 (§7.1)."""
    return _DIR.get(sentiment, 0) * confidence * 100


def _weight(item: dict, now: datetime, half_life: float) -> float:
    age_h = max(0.0, (now - item["posted_at"]).total_seconds() / 3600)
    return (item["credibility"] / 100.0) * 0.5 ** (age_h / half_life)


def timeframe_score(items: list[dict], tf: str, now: datetime) -> dict:
    cutoff = now - timedelta(hours=LOOKBACKS[tf])
    elig = [it for it in items if it["posted_at"] >= cutoff]
    num = den = 0.0
    for it in elig:
        w = _weight(it, now, HALF_LIVES[tf])
        num += w * item_score(it["sentiment"], it["confidence"])
        den += w
    score = round(num / den, 1) if den else None
    return {"score": score, "item_count": len(elig), "low_confidence": len(elig) < MIN_N[tf]}


def aggregate(items: list[dict], now: datetime,
              classifier_tag: str = "mdeberta-v3-xnli@zero-shot-v1"):
    """Returns (headline_score_24h, source_breakdown_json dict)."""
    tfs = {tf: timeframe_score(items, tf, now) for tf in HALF_LIVES}
    counts: dict[str, int] = {}
    for it in items:
        counts[it["source"]] = counts.get(it["source"], 0) + 1

    win = now - timedelta(hours=LOOKBACKS["24h"])
    ranked = sorted(
        ({"market_intel_id": it.get("market_intel_id"), "source": it["source"],
          "author_handle": it.get("author_handle"), "url": it.get("url"),
          "sentiment": it["sentiment"], "sentiment_confidence": round(it["confidence"], 2),
          "item_score": round(item_score(it["sentiment"], it["confidence"]), 2),
          "credibility": round(it["credibility"] / 100.0, 2),
          "weight": round(_weight(it, now, HALF_LIVES["24h"]), 3),
          "posted_at": _iso(it["posted_at"])}
         for it in items if it["posted_at"] >= win),
        key=lambda d: d["weight"], reverse=True)[:5]

    breakdown = {
        "schema_version": 1,
        "computed_at": _iso(now),
        "classifier": classifier_tag,
        "timeframe_scores": tfs,
        "item_counts_by_source": counts,
        "top_contributors": ranked,
    }
    return tfs["24h"]["score"], breakdown
