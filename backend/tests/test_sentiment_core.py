from datetime import datetime, timedelta, timezone

import fakeredis.aioredis
import pytest

from app.sentiment.aggregate import aggregate, item_score, timeframe_score
from app.sentiment.classify import apply_min_conf, apply_weak_label, classify_cached
from app.sentiment.normalize import normalize_for_classify

UTC = timezone.utc
NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


# --- normalize (§4.2) ---

def test_normalize_strips_mentions_urls_keeps_cashtags_emoji():
    out = normalize_for_classify("@user check $AAPL 🚀 #tothemoon https://x.com/a now")
    assert "@user" not in out and "http" not in out
    assert "$AAPL" in out and "🚀" in out and "#tothemoon" in out


def test_normalize_fullwidth_to_halfwidth():
    assert normalize_for_classify("ＡＡＰＬ to the moon") == "AAPL to the moon"


def test_normalize_drops_short_text():
    assert normalize_for_classify("buy") is None


# --- classify rules (§5) ---

def test_apply_min_conf_floor():
    assert apply_min_conf("bullish", 0.9) == ("bullish", 0.9)
    assert apply_min_conf("bullish", 0.30) == ("neutral", 0.30)   # below 0.45 -> neutral, keep conf


def test_apply_weak_label_rule():
    assert apply_weak_label("bullish", 0.6, "bullish") == ("bullish", 0.75)   # agree -> max(0.75,..)
    assert apply_weak_label("bullish", 0.9, "bullish") == ("bullish", 0.9)
    assert apply_weak_label("bullish", 0.8, "bearish") == ("bullish", 0.8)    # disagree -> model
    assert apply_weak_label("bullish", 0.8, None) == ("bullish", 0.8)


@pytest.mark.asyncio
async def test_classify_cached_memoizes():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)

    class FakeClf:
        calls = 0
        def classify_one(self, text):
            FakeClf.calls += 1
            return "bullish", 0.9

    clf = FakeClf()
    assert await classify_cached(r, clf, "samsung mooning today") == ("bullish", 0.9)
    assert await classify_cached(r, clf, "samsung mooning today") == ("bullish", 0.9)
    assert FakeClf.calls == 1   # second call served from Redis cache


# --- aggregation (§7) ---

def test_item_score():
    assert item_score("bullish", 0.91) == pytest.approx(91)
    assert item_score("bearish", 0.74) == pytest.approx(-74)
    assert item_score("neutral", 0.9) == 0


def test_timeframe_score_weighted_decay():
    # 24h, half-life 6h: item A (+100, age0, w=1) + item B (-100, age6h, w=0.5)
    # -> (100 - 50)/(1.0+0.5) = 33.33 -> 33.3
    items = [
        {"sentiment": "bullish", "confidence": 1.0, "credibility": 100, "posted_at": NOW,
         "source": "reddit"},
        {"sentiment": "bearish", "confidence": 1.0, "credibility": 100,
         "posted_at": NOW - timedelta(hours=6), "source": "reddit"},
    ]
    r = timeframe_score(items, "24h", NOW)
    assert r["score"] == pytest.approx(33.3, abs=0.05)
    assert r["item_count"] == 2 and r["low_confidence"] is True   # 2 < N(24h)=10


def test_timeframe_lookback_excludes_old_items():
    items = [
        {"sentiment": "bullish", "confidence": 1.0, "credibility": 100, "posted_at": NOW,
         "source": "reddit"},
        {"sentiment": "bullish", "confidence": 1.0, "credibility": 100,
         "posted_at": NOW - timedelta(hours=30), "source": "reddit"},   # outside 24h window
    ]
    assert timeframe_score(items, "24h", NOW)["item_count"] == 1


def test_aggregate_shape_and_headline():
    items = [{"sentiment": "bullish", "confidence": 0.8, "credibility": 70, "posted_at": NOW,
              "source": "stocktwits", "market_intel_id": 1, "author_handle": "a", "url": "u"}]
    headline, bd = aggregate(items, NOW)
    assert bd["schema_version"] == 1
    assert set(bd["timeframe_scores"]) == {"1h", "5h", "24h", "2d", "3d", "5d"}
    assert headline == bd["timeframe_scores"]["24h"]["score"]
    assert bd["item_counts_by_source"] == {"stocktwits": 1}
    assert bd["top_contributors"][0]["market_intel_id"] == 1
