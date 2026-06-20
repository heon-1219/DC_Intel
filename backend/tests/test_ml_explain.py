"""M5b explainability (prediction-model.md §6). Group aggregation -> positive-only -> top 3 ->
largest-remainder to 100 -> drop <5% + renormalize -> bilingual templates. Oracle: §8.2 example
(sentiment 0.31 / rsi 0.27 / ema 0.14 -> 43 / 38 / 19)."""
import pytest

from app.ml.config import FEATURE_GROUP
from app.ml.explain import (EVIDENCE_TEMPLATES, build_evidence, feature_contributions_lr,
                            largest_remainder_round)


def test_largest_remainder_sums_to_total():
    assert largest_remainder_round([0.31, 0.27, 0.14], total=100) == [43, 38, 19]   # §8.2 oracle
    assert sum(largest_remainder_round([1, 1, 1], total=100)) == 100
    assert largest_remainder_round([5.0], total=100) == [100]
    assert largest_remainder_round([], total=100) == []


def test_template_table_has_all_24_entries():
    groups = ["rsi", "ema", "macd", "bollinger", "volume", "sentiment", "econ_event", "cross_market"]
    assert len(EVIDENCE_TEMPLATES) == 24
    for g in groups:
        for d in ("up", "down", "neutral"):
            assert (g, d) in EVIDENCE_TEMPLATES
    assert EVIDENCE_TEMPLATES[("sentiment", "up")]["en"] == "Positive sentiment surge"
    assert EVIDENCE_TEMPLATES[("rsi", "up")]["ko"] == "RSI 상승 신호"


# §8.2 worked example: the exact contribution_signed values from the doc's features[].
_S82 = {
    "rsi_14": 0.21, "rsi_slope_3": 0.06, "ema_cross_state": 0.10, "ema_bars_since_cross": 0.04,
    "macd_hist_norm": 0.05, "macd_hist_delta": 0.00, "bb_position": -0.03, "vol_z20": 0.08,
    "sent_agg": 0.19, "sent_delta_2h": 0.12, "econ_high_impact_6h": -0.04, "econ_impact_score": -0.02,
    "xmkt_ref_return": 0.09, "xmkt_corr_60d": 0.02, "market_is_krx": 0.01,
}


def test_build_evidence_matches_s82_oracle():
    ev = build_evidence(_S82, FEATURE_GROUP, missing=set(), direction="up")
    assert ev == [
        {"rank": 1, "group": "sentiment", "contribution_pct": 43, "template_key": "sentiment.up",
         "text_en": "Positive sentiment surge (43%)", "text_ko": "긍정적 여론 급증 (43%)"},
        {"rank": 2, "group": "rsi", "contribution_pct": 38, "template_key": "rsi.up",
         "text_en": "RSI bullish signal (38%)", "text_ko": "RSI 상승 신호 (38%)"},
        {"rank": 3, "group": "ema", "contribution_pct": 19, "template_key": "ema.up",
         "text_en": "Bullish EMA crossover (19%)", "text_ko": "EMA 상승 교차 신호 (19%)"},
    ]


def test_build_evidence_excludes_negative_missing_and_aux():
    # only sentiment(+) and rsi(+) push up; bollinger negative excluded; market_is_krx is aux(None).
    contribs = {"sent_agg": 0.6, "rsi_14": 0.4, "bb_position": -0.9, "market_is_krx": 5.0}
    ev = build_evidence(contribs, FEATURE_GROUP, missing=set(), direction="up")
    assert [e["group"] for e in ev] == ["sentiment", "rsi"]    # 2 bullets, aux/negative gone
    assert sum(e["contribution_pct"] for e in ev) == 100


def test_build_evidence_missing_feature_dropped_from_group_sum():
    # sent_delta_2h missing -> sentiment group sum is sent_agg only.
    contribs = {"sent_agg": 0.30, "sent_delta_2h": 0.50, "rsi_14": 0.20}
    ev = build_evidence(contribs, FEATURE_GROUP, missing={"sent_delta_2h"}, direction="up")
    pct = {e["group"]: e["contribution_pct"] for e in ev}
    assert pct == {"sentiment": 60, "rsi": 40}    # 0.30 vs 0.20 -> 60/40 (delta excluded)


def test_build_evidence_drops_below_5pct_and_renormalizes():
    # third group is ~3% -> dropped, remaining two renormalized to 100.
    contribs = {"sent_agg": 0.50, "rsi_14": 0.47, "vol_z20": 0.03}
    ev = build_evidence(contribs, FEATURE_GROUP, missing=set(), direction="up")
    assert [e["group"] for e in ev] == ["sentiment", "rsi"]    # volume (3%) dropped
    assert sum(e["contribution_pct"] for e in ev) == 100


def test_build_evidence_neutral_templates():
    ev = build_evidence({"rsi_14": 0.5, "macd_hist_norm": 0.3}, FEATURE_GROUP,
                        missing=set(), direction="neutral")
    assert ev[0]["template_key"] == "rsi.neutral"
    assert ev[0]["text_en"].startswith("RSI in neutral zone")


def test_feature_contributions_lr():
    c = feature_contributions_lr({"a": 2.0, "b": -1.0}, {"a": 0.5, "b": 3.0})
    assert c == {"a": 1.0, "b": -3.0}    # coef[k][i] * x_std_i
