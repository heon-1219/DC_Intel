"""Real-model checks (excluded from the default run; first run downloads ~1GB). Validate that
the actual mDeBERTa zero-shot classifier and the MiniLM embedder load + infer with the installed
transformers/sentence-transformers versions. Run: pytest backend/tests/test_ml_live.py -m live"""
import pytest

from app.intel.embed import MiniLMEmbedder, cosine
from app.sentiment.classify import ZeroShotClassifier


@pytest.mark.live
def test_live_mdeberta_zero_shot_directions():
    clf = ZeroShotClassifier()
    up, up_c = clf.classify_one("Huge upside, this stock is going to rip higher after earnings")
    down, down_c = clf.classify_one("This will crash hard, sell everything now, terrible outlook")
    assert up == "bullish" and down == "bearish"
    assert 0.0 <= up_c <= 1.0 and 0.0 <= down_c <= 1.0


@pytest.mark.live
def test_live_mdeberta_handles_korean():
    clf = ZeroShotClassifier()
    label, conf = clf.classify_one("삼성전자 오늘 정말 좋아 보인다, 강력 매수 추천")
    assert label in ("bullish", "bearish", "neutral") and 0.0 <= conf <= 1.0


@pytest.mark.live
def test_live_minilm_multilingual_alignment():
    emb = MiniLMEmbedder()
    v = emb.embed(["삼성전자 주가 상승", "Samsung stock is rising", "I had pasta for lunch"])
    assert len(v[0]) == 384
    # cross-lingual same-topic should be closer than same-language off-topic
    assert cosine(v[0], v[1]) > cosine(v[0], v[2])
