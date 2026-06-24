from datetime import date

from app.intel import whisper_config as cfg
from app.intel.whisper.engine import corroborate
from app.intel.whisper.models import WhisperObservation
from app.intel.whisper.weight import build_prior

EARN = date(2026, 7, 1)
PRIOR = build_prior(1.40, EARN)


def _o(value, source, snippet="s"):
    return WhisperObservation(
        value=value, raw_value=str(value), source=source, source_family=cfg.source_family(source),
        source_credibility_prior=cfg.source_prior(source), as_of_date=EARN, context_snippet=snippet)


class FakeFetcher:
    def __init__(self, by_source):
        self.by_source = by_source
        self.calls = []

    def fetch(self, source):
        self.calls.append(source)
        return list(self.by_source.get(source, []))


def test_no_anchor_abstains():
    r = corroborate(None, FakeFetcher({}), today=EARN)
    assert r.status == "no_reliable_whisper" and r.abstain_reason == "NO_ANCHOR"


def test_no_observations_abstains():
    r = corroborate(PRIOR, FakeFetcher({}), today=EARN)
    assert r.abstain_reason == "NO_OBSERVATIONS"


def test_stop_confirm_does_not_fetch_noisier_tiers():
    # 3 agreeing obs across 3 families (ews + estimize in tier A, websearch in tier B) -> corroborated
    # at round 2, so tier C (forum/stocktwits) is never fetched.
    f = FakeFetcher({
        "earningswhispers": [_o(1.43, "earningswhispers", "a")],
        "estimize": [_o(1.43, "estimize", "b")],
        "websearch": [_o(1.43, "websearch", "c")],
        "forum": [_o(1.43, "forum", "d")],
    })
    r = corroborate(PRIOR, f, today=EARN)
    assert r.status == "corroborated"
    assert r.whisper_value == 1.43 and r.n_distinct_families == 3
    assert r.rounds_used == 2
    assert "forum" not in f.calls and "stocktwits" not in f.calls  # STOP-CONFIRM


def test_high_trust_single_earningswhispers_override():
    f = FakeFetcher({"earningswhispers": [_o(1.45, "earningswhispers")]})
    r = corroborate(PRIOR, f, today=EARN)
    assert r.status == "tentative" and r.whisper_value == 1.45
    assert r.confidence <= cfg.SINGLE_FAMILY_CAP and r.n_distinct_families == 1


def test_unresolved_contention_abstains():
    # two well-supported clusters (1.40 vs 1.75), each backed by 3 families, neither dominating ->
    # the engine refuses to average two contradictory truths.
    f = FakeFetcher({
        "earningswhispers": [_o(1.40, "earningswhispers", "a"), _o(1.75, "earningswhispers", "b")],
        "estimize": [_o(1.40, "estimize", "c"), _o(1.75, "estimize", "d")],
        "websearch": [_o(1.40, "websearch", "e"), _o(1.75, "websearch", "f")],
    })
    r = corroborate(PRIOR, f, today=EARN)
    assert r.status == "no_reliable_whisper" and r.abstain_reason == "UNRESOLVED_CONTENTION"


def test_stop_no_gain_halts_escalation():
    # tier A: 2 estimize obs (1 family, <MIN_OBS, no ews override). tier B websearch empty -> no gain
    # at idx>0 -> STOP-NO-GAIN, so tier C never fetched; final = INSUFFICIENT_INLIERS.
    f = FakeFetcher({"estimize": [_o(1.40, "estimize", "a"), _o(1.41, "estimize", "b")]})
    r = corroborate(PRIOR, f, today=EARN)
    assert r.abstain_reason == "INSUFFICIENT_INLIERS"
    assert "forum" not in f.calls and "stocktwits" not in f.calls
