from datetime import date

import pytest

from app.intel import whisper_config as cfg
from app.intel.whisper.models import WhisperObservation
from app.intel.whisper.weight import build_prior, evaluate

EARN = date(2026, 7, 1)


def _obs(value, as_of, source="earningswhispers", prior=0.85, snippet="x"):
    return WhisperObservation(
        value=value, raw_value=str(value), source=source,
        source_family=cfg.source_family(source), source_credibility_prior=prior,
        as_of_date=as_of, context_snippet=snippet)


def test_build_prior():
    p = build_prior(1.40, EARN)
    assert p.mu0 == 1.40 and p.anchor_scale == pytest.approx(1.40)
    assert build_prior(None, EARN) is None
    assert build_prior(1.4, None) is None
    assert build_prior(0.02, EARN).anchor_scale == pytest.approx(cfg.MIN_SCALE)  # near-zero floored


def test_recency_halflife():
    p = build_prior(1.40, EARN)
    assert evaluate(_obs(1.45, EARN), p, today=EARN).recency_weight == pytest.approx(1.0)
    aged = evaluate(_obs(1.45, date(2026, 6, 17)), p, today=EARN)  # 14 days old
    assert aged.recency_weight == pytest.approx(0.5)


def test_post_report_observation_is_stale():
    p = build_prior(1.40, EARN)
    r = evaluate(_obs(1.50, date(2026, 7, 2)), p, today=date(2026, 7, 3))
    assert not r.kept and r.reject_reason == "stale"


def test_beyond_stale_window_rejected():
    p = build_prior(1.40, EARN)
    r = evaluate(_obs(1.45, date(2026, 5, 1)), p, today=EARN)  # > 45 days before earnings
    assert not r.kept and r.reject_reason == "stale"


def test_implausible_far_from_anchor_rejected():
    p = build_prior(1.40, EARN)  # scale 1.40; rel_dev>0.60 => reject
    r = evaluate(_obs(3.00, EARN), p, today=EARN)  # rel_dev = 1.6/1.4 = 1.14
    assert not r.kept and r.reject_reason == "implausible"


def test_sign_flip_is_implausible():
    p = build_prior(1.00, EARN)
    r = evaluate(_obs(-0.50, EARN), p, today=EARN)  # opposite sign => rel_dev=1.5 > ABSURD_REL
    assert not r.kept and r.reject_reason == "implausible"


def test_kept_weight_is_prior_when_fresh_and_plausible():
    p = build_prior(1.40, EARN)
    o = evaluate(_obs(1.45, EARN, prior=0.85), p, today=EARN)
    # rel_dev 0.0357 <= soft -> plaus 1.0; recency 1.0; sign ok -> weight = prior
    assert o.kept and o.weight == pytest.approx(0.85)


def test_soft_plausibility_ramp():
    p = build_prior(1.00, EARN)  # scale 1.00
    o = evaluate(_obs(1.45, EARN, prior=0.80), p, today=EARN)  # rel_dev 0.45 in (0.30, 0.60)
    expected_plaus = (cfg.ABSURD_REL - 0.45) / (cfg.ABSURD_REL - cfg.ABSURD_REL_SOFT)  # 0.5
    assert o.kept and o.weight == pytest.approx(0.80 * expected_plaus)
