import pytest

from app.intel.credibility import (band, credibility, subscore_a, subscore_c, subscore_e,
                                   subscore_s)


def test_credibility_worked_example():
    # §6.3: S=70, A=40, C=75, E=91 -> 0.30·70+0.30·40+0.25·75+0.15·91 = 65.4 -> 65
    assert credibility(70, 40, 75, 91) == 65


def test_credibility_news_example():
    # §6: round(0.30·70 + 0.30·50 + 0.25·50 + 0.15·25) = 52
    assert credibility(70, 50, 50, 25) == 52


def test_coordinated_cap_and_clamp():
    assert credibility(90, 90, 100, 100, coordinated=True) == 20
    assert 0 <= credibility(0, 0, 0, 0) <= 100


def test_subscore_a_laplace():
    assert subscore_a(8, 3) == pytest.approx(40.0)     # 100·4/10
    assert subscore_a(None, None) == 50.0              # unknown author
    assert subscore_a(0, 0) == pytest.approx(50.0)     # 100·1/2


def test_subscore_c_corroboration():
    # C = 25·(n−1): 1 author->0, 2->25, 3->50, 4->75 (§6.3 example n=4 -> 75)
    assert subscore_c(1) == 0 and subscore_c(2) == 25
    assert subscore_c(3) == 50 and subscore_c(4) == 75
    assert subscore_c(10) == 100   # capped


def test_subscore_e():
    assert subscore_e(None, None) == 25                # no profile data
    assert subscore_e(730, 12400) == 91                # 2yr + 12.4k karma (§6.3)


def test_subscore_s_tiers():
    assert subscore_s("reddit") == 70
    assert subscore_s("dcinside") == 30 and subscore_s("naver") == 30
    assert subscore_s("twitter") == 50
    assert subscore_s("finnhub", "reuters.com") == 90      # tier-1 outlet
    assert subscore_s("newsapi", "sometabloid.com") == 70  # other outlet


def test_band():
    assert band(80) == "high" and band(60) == "moderate"
    assert band(30) == "low" and band(10) == "very_low"
