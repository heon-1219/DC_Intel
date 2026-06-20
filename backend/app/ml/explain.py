"""Explainability — turn per-feature contributions into <=3 bilingual evidence bullets
(prediction-model.md §6). Pure (no ML libs): contributions are computed upstream (LR coef x std,
or XGB SHAP) and passed in. Algorithm (§6.2): sum signed contributions per group (excluding missing
and auxiliary features) -> keep only groups pushing TOWARD the displayed direction -> top 3 by
magnitude -> normalize to 100% via largest remainder -> drop any bullet < 5% and renormalize ->
render the {group}.{direction} template. Oracle: §8.2 (sentiment 0.31/rsi 0.27/ema 0.14 -> 43/38/19)."""
from collections import defaultdict

# §6.3 — bilingual template table: (group, direction) -> {en, ko}. 8 groups x 3 directions = 24.
EVIDENCE_TEMPLATES = {
    ("rsi", "up"): {"en": "RSI bullish signal", "ko": "RSI 상승 신호"},
    ("rsi", "down"): {"en": "RSI bearish signal", "ko": "RSI 하락 신호"},
    ("rsi", "neutral"): {"en": "RSI in neutral zone", "ko": "RSI 중립 구간"},
    ("ema", "up"): {"en": "Bullish EMA crossover", "ko": "EMA 상승 교차 신호"},
    ("ema", "down"): {"en": "Bearish EMA crossover", "ko": "EMA 하락 교차 신호"},
    ("ema", "neutral"): {"en": "No clear EMA trend", "ko": "EMA 추세 뚜렷하지 않음"},
    ("macd", "up"): {"en": "MACD momentum rising", "ko": "MACD 모멘텀 상승"},
    ("macd", "down"): {"en": "MACD momentum falling", "ko": "MACD 모멘텀 하락"},
    ("macd", "neutral"): {"en": "MACD momentum fading", "ko": "MACD 모멘텀 약화"},
    ("bollinger", "up"): {"en": "Price in Bollinger buy zone", "ko": "볼린저 밴드 매수 구간"},
    ("bollinger", "down"): {"en": "Price in Bollinger sell zone", "ko": "볼린저 밴드 매도 구간"},
    ("bollinger", "neutral"): {"en": "Price mid-range of Bollinger bands", "ko": "볼린저 밴드 중앙 구간"},
    ("volume", "up"): {"en": "Unusual volume surge with buyers", "ko": "거래량 급증 (매수 우위)"},
    ("volume", "down"): {"en": "Unusual volume surge with sellers", "ko": "거래량 급증 (매도 우위)"},
    ("volume", "neutral"): {"en": "Volume back to normal", "ko": "거래량 평소 수준"},
    ("sentiment", "up"): {"en": "Positive sentiment surge", "ko": "긍정적 여론 급증"},
    ("sentiment", "down"): {"en": "Negative sentiment surge", "ko": "부정적 여론 급증"},
    ("sentiment", "neutral"): {"en": "Mixed sentiment", "ko": "여론 혼조"},
    ("econ_event", "up"): {"en": "Economic event tailwind", "ko": "경제 일정 호재 영향"},
    ("econ_event", "down"): {"en": "Economic event risk ahead", "ko": "경제 일정 리스크 임박"},
    ("econ_event", "neutral"): {"en": "Waiting on major economic event", "ko": "주요 경제 일정 대기"},
    ("cross_market", "up"): {"en": "Overseas market moved up overnight", "ko": "해외 시장 야간 상승"},
    ("cross_market", "down"): {"en": "Overseas market moved down overnight", "ko": "해외 시장 야간 하락"},
    ("cross_market", "neutral"): {"en": "Overseas markets flat", "ko": "해외 시장 보합"},
}

EVIDENCE_MIN_PCT = 5   # §6.2 step 5 — drop bullets below this and renormalize (config/ml.yaml)


def feature_contributions_lr(coef_row: dict, x_std: dict) -> dict:
    """§6.1 LR: signed contribution c_i = coef[k][i] * x_std_i toward the displayed class k."""
    return {f: coef_row[f] * x_std[f] for f in coef_row}


def largest_remainder_round(values: list[float], total: int = 100) -> list[int]:
    """Distribute `total` across `values` proportionally with integer results summing exactly to
    `total` (Hamilton / largest-remainder method). Empty or all-zero input -> zeros."""
    if not values:
        return []
    s = sum(values)
    if s <= 0:
        return [0] * len(values)
    quotas = [v / s * total for v in values]
    floors = [int(q) for q in quotas]
    remainder = total - sum(floors)
    # hand the leftover units to the largest fractional parts (ties -> earlier index).
    order = sorted(range(len(values)), key=lambda i: (quotas[i] - floors[i], -i), reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def _render(group: str, direction: str, pct: int, rank: int) -> dict:
    tpl = EVIDENCE_TEMPLATES[(group, direction)]
    return {
        "rank": rank, "group": group, "contribution_pct": pct,
        "template_key": f"{group}.{direction}",
        "text_en": f"{tpl['en']} ({pct}%)", "text_ko": f"{tpl['ko']} ({pct}%)",
    }


def build_evidence(contribs: dict, group_of: dict, missing: set, direction: str) -> list[dict]:
    """§6.2 — see module docstring. `contribs` is feature -> signed contribution toward the
    displayed direction; `group_of` maps feature -> group (None for auxiliary)."""
    g = defaultdict(float)
    for feat, c in contribs.items():
        if feat in missing or group_of.get(feat) is None:
            continue
        g[group_of[feat]] += c
    pos = {grp: v for grp, v in g.items() if v > 0}                       # toward direction only
    top = sorted(pos.items(), key=lambda kv: -kv[1])[:3]                  # top 3 by magnitude
    pcts = largest_remainder_round([v for _, v in top], total=100)
    keep = [(grp, p) for (grp, _), p in zip(top, pcts) if p >= EVIDENCE_MIN_PCT]
    if len(keep) < len(top):                                             # dropped <5% -> renormalize
        pcts = largest_remainder_round([g[grp] for grp, _ in keep], total=100)
        keep = [(grp, p) for (grp, _), p in zip(keep, pcts)]
    return [_render(grp, direction, pct, i + 1) for i, (grp, pct) in enumerate(keep)]
