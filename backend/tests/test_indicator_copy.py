import pytest

from app.services import indicator_copy as copy


def test_rsi_copy_overbought_en_ko():
    assert copy.rsi_copy(74, "overbought", "en") == "RSI overbought (74/70) → pullback risk"
    assert copy.rsi_copy(74, "overbought", "ko") == "RSI 과매수 (74/70) → 하락 전환 주의"


def test_rsi_copy_rounds_value_to_int():
    assert copy.rsi_copy(73.4, "bullish", "en") == "RSI strong (73) → buyers in control"
    assert copy.rsi_copy(27.2, "oversold", "en") == "RSI oversold (27/30) → bounce possible"


def test_ema_cross_copy_intraday_vs_daily_naming():
    # 50/200 up-cross is "golden cross" only on daily bars; "trend shift" intraday.
    assert "Golden cross" in copy.ema_cross_copy(50, 200, 1, "1d", "en")
    assert "Trend shift up" in copy.ema_cross_copy(50, 200, 1, "5m", "en")
    assert "골든 크로스" in copy.ema_cross_copy(50, 200, 1, "1d", "ko")


def test_ema_intraday_down_cross_copy():
    # §5.4 — symmetric intraday EMA50x200 down-cross (no golden/death naming intraday).
    assert copy.ema_cross_copy(50, 200, -1, "5m", "en") == \
        "Trend shift down on short charts → weakening"
    assert copy.ema_cross_copy(50, 200, -1, "1h", "ko") == \
        "단기 차트 추세 하락 전환 → 약세 심화"


def test_ema_short_cross_copy():
    assert copy.ema_cross_copy(5, 20, 1, "5m", "en") == \
        "Short-term momentum turned up (5/20 cross) → upward push"
    assert copy.ema_cross_copy(5, 20, -1, "5m", "en") == \
        "Short-term momentum turned down (5/20 cross) → downward push"


def test_macd_copy_bullish_cross():
    assert copy.macd_copy("bullish_cross", "en") == \
        "Momentum flipped up (MACD cross) → buyers stepping in"
    assert copy.macd_copy("bullish_cross", "ko") == "모멘텀 상승 전환 (MACD 교차) → 매수세 유입"


def test_bollinger_copy_breakout_up():
    assert copy.bollinger_copy("breakout_up", "en") == \
        "Price broke above its normal range → upside breakout"


def test_volume_label_one_decimal():
    assert copy.vol_label(1.9, "en") == "Volume 1.9σ above normal"
    assert copy.vol_label(1.9, "ko") == "거래량 평소 대비 1.9σ 증가"


def test_short_evidence_forms():
    # §12 short canonical forms used when all 3 bullet slots are filled / mobile.
    assert copy.short_evidence("rsi", "overbought", "en") == "RSI overbought signal"
    assert copy.short_evidence("ema", "ema_5_20_up", "en") == "EMA crossover"
    assert copy.short_evidence("macd", "bullish_cross", "en") == "MACD momentum up"
    assert copy.short_evidence("bollinger", "breakout_up", "en") == "Range breakout up"


def test_direction_for_state():
    # color semantics: bullish->green, bearish->red, neutral/squeeze->gray
    assert copy.direction_for_state("rsi", "overbought") == "down"
    assert copy.direction_for_state("rsi", "oversold") == "up"
    assert copy.direction_for_state("rsi", "neutral") == "neutral"
    assert copy.direction_for_state("bollinger", "squeeze") == "neutral"
