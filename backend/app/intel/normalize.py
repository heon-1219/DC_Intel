"""Cleaning + language tag + content hash for market-intel (market-intel-pipeline.md §4.1, §4.3).
content_snippet keeps original language/casing; URLs stripped from body; <=500 chars."""
import hashlib
import re
import unicodedata

_URL = re.compile(r"https?://\S+")
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_HANGUL = re.compile(r"[가-힣]")
_ALPHA = re.compile(r"[^\W\d_]", re.UNICODE)


def clean_snippet(text: str, max_chars: int = 500) -> str:
    """Strip URLs, collapse whitespace, truncate. Preserves casing + language."""
    t = _URL.sub("", text or "")
    t = _WS.sub(" ", t).strip()
    return t[:max_chars]


def detect_lang(text: str) -> str:
    """'ko' if >=30% of alphabetic chars are Hangul, else 'en' (render-time rule, §11)."""
    alpha = _ALPHA.findall(text or "")
    if not alpha:
        return "en"
    hangul = len(_HANGUL.findall(text))
    return "ko" if hangul / len(alpha) >= 0.30 else "en"


def text_hash(text: str) -> str:
    """SHA-256 of lowercased, punctuation- and whitespace-stripped text (exact-dup key, §4.3)."""
    norm = _PUNCT.sub("", (text or "").lower())
    norm = _WS.sub("", norm)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
