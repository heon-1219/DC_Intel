from datetime import date

import pytest

from app.intel import whisper_config as cfg
from app.intel.whisper.models import WhisperCluster, WhisperObservation
from app.intel.whisper.score import classify, dominance, meaningfulness
from app.intel.whisper.weight import build_prior

PRIOR = build_prior(1.40, date(2026, 7, 1))


def _inlier(value, source, weight, recency=1.0, age=0):
    return WhisperObservation(
        value=value, raw_value=str(value), source=source, source_family=cfg.source_family(source),
        source_credibility_prior=cfg.source_prior(source), as_of_date=date(2026, 7, 1),
        weight=weight, recency_weight=recency, age_days=age)


def test_factors_isolated():
    ins = [_inlier(1.45, "earningswhispers", 0.85), _inlier(1.45, "estimize", 0.75),
           _inlier(1.45, "websearch", 0.45)]
    conf, f = meaningfulness(ins, center=1.45, inlier_dispersion=0.0, n_distinct_families=3,
                             coordinated=False, prior=PRIOR)
    assert f["f_count"] == pytest.approx(1.0)          # 3/3 families
    assert f["f_agree"] == pytest.approx(1.0)          # dispersion 0
    # rel_dev_center = 0.05/1.40 = 0.0357 -> f_anchor = 1 - 0.0357/0.60
    assert f["f_anchor"] == pytest.approx(1 - (0.05 / 1.40) / cfg.ABSURD_REL, abs=1e-3)
    assert 0 <= conf <= 100


def test_single_family_cap():
    ins = [_inlier(1.45, "forum", 0.30), _inlier(1.45, "forum", 0.30)]
    conf, f = meaningfulness(ins, 1.45, 0.0, n_distinct_families=1, coordinated=False, prior=PRIOR)
    assert conf <= cfg.SINGLE_FAMILY_CAP and "single_family" in f["caps"]


def test_coordinated_cap():
    ins = [_inlier(1.45, "forum", 0.30) for _ in range(3)]
    conf, f = meaningfulness(ins, 1.45, 0.0, n_distinct_families=1, coordinated=True, prior=PRIOR)
    assert conf <= cfg.COORDINATED_CAP and "coordinated" in f["caps"]


def test_stale_cap():
    ins = [_inlier(1.45, "earningswhispers", 0.5, recency=0.3, age=30),
           _inlier(1.45, "estimize", 0.5, recency=0.3, age=30)]
    conf, f = meaningfulness(ins, 1.45, 0.0, n_distinct_families=2, coordinated=False, prior=PRIOR)
    assert conf <= cfg.STALE_CAP and "stale" in f["caps"]


def test_dominance():
    win = WhisperCluster(value=1.45, members=(), n_distinct_families=2, support_mass=1.0,
                         weighted_dispersion=0.0)
    runner = WhisperCluster(value=1.20, members=(), n_distinct_families=1, support_mass=0.7,
                            weighted_dispersion=0.0)
    assert dominance(win, runner) == pytest.approx(0.3)
    assert dominance(win, None) == 1.0


def test_classify_bands():
    assert classify(80, n_distinct_families=2, coordinated=False, dom=1.0, inlier_dispersion=0.0) == "corroborated"
    assert classify(60, n_distinct_families=2, coordinated=False, dom=1.0, inlier_dispersion=0.0) == "tentative"
    assert classify(50, n_distinct_families=2, coordinated=False, dom=1.0, inlier_dispersion=0.0) == "no_reliable_whisper"
    # high confidence but single family -> cannot be corroborated, only tentative
    assert classify(80, n_distinct_families=1, coordinated=False, dom=1.0, inlier_dispersion=0.0) == "tentative"
