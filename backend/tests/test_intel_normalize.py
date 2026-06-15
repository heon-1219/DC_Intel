from app.intel.normalize import clean_snippet, detect_lang, text_hash


def test_clean_snippet_strips_urls_and_collapses_ws():
    s = clean_snippet("Buy   $AAPL now https://x.com/a/b   🚀  big move")
    assert "http" not in s
    assert s == "Buy $AAPL now 🚀 big move"   # whitespace collapsed, emoji kept


def test_clean_snippet_truncates():
    assert len(clean_snippet("a" * 1000, max_chars=500)) == 500


def test_detect_lang_korean_vs_english():
    assert detect_lang("삼성전자 오늘 떡상 가즈아") == "ko"
    assert detect_lang("Samsung is going to rip today") == "en"
    assert detect_lang("삼성 buy the dip now please ok") == "en"   # <30% hangul
    assert detect_lang("12345 $$$ ???") == "en"                    # no alpha -> en


def test_text_hash_ignores_case_punct_ws():
    assert text_hash("To the MOON!!!") == text_hash("to  the moon")
    assert text_hash("buy aapl") != text_hash("sell aapl")
