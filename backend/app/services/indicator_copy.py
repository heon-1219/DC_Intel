"""EN/KO copy templates for indicator signal states. Source: technical-indicators.md
§4.4, §5.4, §6.4, §7.4, §7A.4, §12. Pure string functions."""

_RSI = {
    "overbought": ("RSI overbought ({v}/70) → pullback risk", "RSI 과매수 ({v}/70) → 하락 전환 주의"),
    "bullish":    ("RSI strong ({v}) → buyers in control",      "RSI 강세 ({v}) → 매수세 우위"),
    "neutral":    ("RSI neutral ({v}) → no clear pressure",     "RSI 중립 ({v}) → 뚜렷한 방향 없음"),
    "bearish":    ("RSI weak ({v}) → sellers in control",       "RSI 약세 ({v}) → 매도세 우위"),
    "oversold":   ("RSI oversold ({v}/30) → bounce possible",   "RSI 과매도 ({v}/30) → 반등 가능"),
}

_MACD = {
    "bullish_cross":     ("Momentum flipped up (MACD cross) → buyers stepping in",
                          "모멘텀 상승 전환 (MACD 교차) → 매수세 유입"),
    "bearish_cross":     ("Momentum flipped down (MACD cross) → sellers stepping in",
                          "모멘텀 하락 전환 (MACD 교차) → 매도세 유입"),
    "zero_cross_up":     ("Momentum turned positive → uptrend confirmed",
                          "모멘텀 플러스 전환 → 상승 추세 확인"),
    "zero_cross_down":   ("Momentum turned negative → downtrend confirmed",
                          "모멘텀 마이너스 전환 → 하락 추세 확인"),
    "momentum_building": ("Upward momentum building → trend strengthening",
                          "상승 모멘텀 확대 → 추세 강화"),
    "momentum_fading":   ("Momentum fading → current trend losing steam",
                          "모멘텀 약화 → 현재 추세 둔화"),
}

_BOLL = {
    "squeeze":      ("Price range tightening → big move brewing (direction unclear)",
                     "가격 변동폭 축소 → 큰 움직임 임박 (방향 미정)"),
    "breakout_up":  ("Price broke above its normal range → upside breakout",
                     "평소 범위 위로 돌파 → 상승 돌파"),
    "breakout_down":("Price broke below its normal range → downside break",
                     "평소 범위 아래로 이탈 → 하락 이탈"),
    "riding_upper": ("Price hugging the top of its range → strong demand",
                     "범위 상단 유지 → 강한 매수세"),
    "riding_lower": ("Price hugging the bottom of its range → strong selling",
                     "범위 하단 유지 → 강한 매도세"),
    "squeeze_breakout_up": ("Tight range broke upward → sharp rise often follows",
                            "좁은 범위 상향 돌파 → 급등 가능성"),
}

_SHORT = {
    ("rsi", "overbought"): ("RSI overbought signal", "RSI 과매수 신호"),
    ("rsi", "oversold"):   ("RSI oversold signal", "RSI 과매도 신호"),
    ("rsi", "bullish"):    ("RSI bullish signal", "RSI 강세 신호"),
    ("rsi", "bearish"):    ("RSI bearish signal", "RSI 약세 신호"),
    ("ema", "ema_5_20_up"):   ("EMA crossover", "EMA 교차"),
    ("ema", "ema_5_20_down"): ("EMA crossover", "EMA 교차"),
    ("macd", "bullish_cross"): ("MACD momentum up", "MACD 모멘텀 상승"),
    ("macd", "bearish_cross"): ("MACD momentum down", "MACD 모멘텀 하락"),
    ("bollinger", "breakout_up"):   ("Range breakout up", "범위 상향 돌파"),
    ("bollinger", "breakout_down"): ("Range breakout down", "범위 하향 이탈"),
}

# state -> direction for color semantics (green=up, red=down, gray=neutral). §12.
_DIRECTION = {
    ("rsi", "overbought"): "down", ("rsi", "bullish"): "up", ("rsi", "neutral"): "neutral",
    ("rsi", "bearish"): "down", ("rsi", "oversold"): "up",
    ("macd", "bullish_cross"): "up", ("macd", "bearish_cross"): "down",
    ("macd", "zero_cross_up"): "up", ("macd", "zero_cross_down"): "down",
    ("macd", "momentum_building"): "up", ("macd", "momentum_fading"): "neutral",
    ("macd", "neutral"): "neutral",
    ("bollinger", "breakout_up"): "up", ("bollinger", "breakout_down"): "down",
    ("bollinger", "riding_upper"): "up", ("bollinger", "riding_lower"): "down",
    ("bollinger", "squeeze"): "neutral", ("bollinger", "inside"): "neutral",
}


def _pick(en_ko: tuple, lang: str) -> str:
    return en_ko[1] if lang == "ko" else en_ko[0]


def rsi_copy(value: float, state: str, lang: str) -> str:
    return _pick(_RSI[state], lang).format(v=round(value))


def ema_cross_copy(fast: int, slow: int, cross_dir: int, bar_interval: str, lang: str) -> str:
    if (fast, slow) == (5, 20):
        if cross_dir > 0:
            return _pick(("Short-term momentum turned up (5/20 cross) → upward push",
                          "단기 흐름 상승 전환 (5/20 골든) → 상승 압력"), lang)
        return _pick(("Short-term momentum turned down (5/20 cross) → downward push",
                      "단기 흐름 하락 전환 (5/20 데드) → 하락 압력"), lang)
    # 50/200 pair: golden/death naming only on daily bars (§5.4)
    if bar_interval == "1d":
        if cross_dir > 0:
            return _pick(("Golden cross (50/200) → long-term trend turning up",
                          "골든 크로스 (50/200) → 장기 추세 상승 전환"), lang)
        return _pick(("Death cross (50/200) → long-term trend turning down",
                      "데드 크로스 (50/200) → 장기 추세 하락 전환"), lang)
    if cross_dir > 0:
        return _pick(("Trend shift up on short charts → strengthening",
                      "단기 차트 추세 상승 전환 → 강세 강화"), lang)
    return _pick(("Trend shift down on short charts → weakening",
                  "단기 차트 추세 하락 전환 → 약세 심화"), lang)


def macd_copy(state: str, lang: str) -> str:
    return _pick(_MACD[state], lang)


def bollinger_copy(state: str, lang: str) -> str:
    return _pick(_BOLL[state], lang)


def vol_label(z: float, lang: str) -> str:
    return _pick(("Volume {z}σ above normal", "거래량 평소 대비 {z}σ 증가"),
                 lang).format(z=round(z, 1))


def short_evidence(group: str, state: str, lang: str) -> str:
    return _pick(_SHORT[(group, state)], lang)


def direction_for_state(group: str, state: str) -> str:
    return _DIRECTION.get((group, state), "neutral")
