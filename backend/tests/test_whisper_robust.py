import pytest

from app.intel.whisper.robust import is_inlier, scaled_mad, weighted_median


def test_weighted_median_basic_and_ties():
    assert weighted_median([(1, 1), (2, 1), (3, 1)]) == 2
    assert weighted_median([(5, 1), (5, 1)]) == 5            # all equal
    assert weighted_median([(7, 2)]) == 7                    # single
    assert weighted_median([(1, 1), (3, 1)]) == 1            # even split -> lower-value tie-break
    assert weighted_median([]) is None


def test_weighted_median_weight_pulls_center():
    # the heavy observation dominates
    assert weighted_median([(1, 1), (10, 5)]) == 10


def test_weighted_median_zero_weights_falls_back():
    assert weighted_median([(1, 0), (2, 0), (3, 0)]) == 2    # plain lower-median


def test_scaled_mad():
    smad = scaled_mad([(1, 1), (2, 1), (3, 1)], center=2)
    assert smad == pytest.approx(1.4826)                     # median |dev| = 1
    assert scaled_mad([(5, 1), (5, 1)], center=5) == 0.0     # identical -> 0
    assert scaled_mad([], center=0) == 0.0


def test_is_inlier_boundary():
    # center 0, smad 1, k 3 -> threshold 3.0
    assert is_inlier(3.0, center=0, smad=1.0, mad_k=3.0) is True
    assert is_inlier(3.01, center=0, smad=1.0, mad_k=3.0) is False


def test_is_inlier_degenerate_cluster():
    # smad == 0 -> only an exact match counts
    assert is_inlier(5.0, center=5.0, smad=0.0) is True
    assert is_inlier(5.1, center=5.0, smad=0.0) is False
