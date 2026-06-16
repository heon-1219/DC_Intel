"""Zero-shot sentiment classifier (sentiment-pipeline.md §5). transformers is lazy-imported so
the offline suite injects a fake classifier and never loads the 280M-param model. The pure
rules (min-conf floor §5, StockTwits weak-label §5.4) are unit-tested without the model; the
real mDeBERTa pipeline is covered by a @pytest.mark.live test."""
import hashlib
import json

from app.intel.config import SENTIMENT_CLF_MIN_CONF, SENTIMENT_CLF_MODEL

LABELS = ["bullish", "bearish", "neutral"]
HYPOTHESIS = "The author of this post is {} about this stock's price."


def apply_min_conf(label: str, conf: float, min_conf: float = SENTIMENT_CLF_MIN_CONF):
    """Below the confidence floor → neutral, but keep the (low) confidence value (§5)."""
    if conf < min_conf:
        return "neutral", conf
    return label, conf


def apply_weak_label(model_label: str, model_conf: float, weak_label: str | None):
    """StockTwits self-tag (§5.4): agree → use the tag at conf max(0.75, model); disagree → model."""
    if weak_label and weak_label == model_label:
        return weak_label, max(0.75, model_conf)
    return model_label, model_conf


class ZeroShotClassifier:
    name = "mdeberta-v3-xnli@zero-shot-v1"

    def __init__(self, model_name: str = SENTIMENT_CLF_MODEL):
        self.model_name = model_name
        self._pipe = None

    def _load(self):
        if self._pipe is None:
            from transformers import pipeline  # lazy: heavy
            self._pipe = pipeline("zero-shot-classification", model=self.model_name, device=-1)
        return self._pipe

    def classify_one(self, text: str):
        r = self._load()(text, LABELS, hypothesis_template=HYPOTHESIS, multi_label=False)
        return r["labels"][0], float(r["scores"][0])


async def classify_cached(redis, classifier, text: str, weak_label: str | None = None):
    """Classify with Redis memoization (§5, key sentiment:clf:{sha1}, TTL 7d) + min-conf floor +
    weak-label rule. `classifier` exposes classify_one(text) -> (label, conf)."""
    key = f"sentiment:clf:{hashlib.sha1(text.encode('utf-8')).hexdigest()}"
    cached = await redis.get(key)
    if cached:
        d = json.loads(cached)
        label, conf = d["label"], d["confidence"]
    else:
        raw_label, raw_conf = classifier.classify_one(text)
        label, conf = apply_min_conf(raw_label, raw_conf)
        await redis.set(key, json.dumps({"label": label, "confidence": conf}), ex=7 * 24 * 3600)
    return apply_weak_label(label, conf, weak_label)
