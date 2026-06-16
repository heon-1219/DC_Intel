"""Classifier-input preprocessing (sentiment-pipeline.md §4.2), in spec order: NFC; fullwidth→
halfwidth; strip URLs + @mentions (keep cashtags/hashtags); collapse whitespace; keep emoji;
drop items < SENTIMENT_MIN_TEXT_LEN chars (returns None). Token truncation is the tokenizer's job."""
import re
import unicodedata

from app.intel.config import SENTIMENT_MIN_TEXT_LEN

_URL = re.compile(r"https?://\S+")
_MENTION = re.compile(r"@\w+")
_WS = re.compile(r"\s+")


def _halfwidth(ch: str) -> str:
    o = ord(ch)
    if 0xFF01 <= o <= 0xFF5E:        # fullwidth ASCII → halfwidth
        return chr(o - 0xFEE0)
    if o == 0x3000:                  # ideographic space → normal space
        return " "
    return ch


def normalize_for_classify(text: str, min_len: int = SENTIMENT_MIN_TEXT_LEN) -> str | None:
    t = unicodedata.normalize("NFC", text or "")
    t = "".join(_halfwidth(c) for c in t)
    t = _MENTION.sub("", _URL.sub("", t))
    t = _WS.sub(" ", t).strip()
    return t if len(t) >= min_len else None
