from datetime import date

from app.intel import whisper_config as cfg
from app.intel.whisper.cluster import cluster_values, dedup_by_family, refine_inliers
from app.intel.whisper.models import WhisperCluster, WhisperObservation

EARN = date(2026, 7, 1)


def _o(value, source, weight, snippet="s"):
    return WhisperObservation(
        value=value, raw_value=str(value), source=source, source_family=cfg.source_family(source),
        source_credibility_prior=cfg.source_prior(source), as_of_date=EARN, context_snippet=snippet,
        weight=weight, kept=True)


def test_dedup_collapses_verbatim_family_echo():
    obs = [_o(1.50, "forum", 0.3, "MU whisper 1.50"), _o(1.50, "forum", 0.3, "MU whisper 1.50")]
    assert len(dedup_by_family(obs)) == 1  # same family+value+snippet -> one contribution


def test_two_separated_clusters():
    obs = [_o(1.40, "earningswhispers", 0.8, "a"), _o(1.42, "estimize", 0.7, "b"),
           _o(1.80, "websearch", 0.4, "c")]
    clusters = cluster_values(obs, anchor_scale=1.40)  # tol = max(0.01, 0.028) = 0.028
    assert len(clusters) == 2
    assert clusters[0].support_mass >= clusters[1].support_mass  # sorted by support
    top = clusters[0]
    assert top.n_distinct_families == 2 and 1.40 <= top.value <= 1.42


def test_coordinated_forum_flood_flagged():
    obs = [_o(1.50, "forum", 0.3, f"echo{i}") for i in range(3)]  # 3 low-weight forum, no purpose-built
    cluster = cluster_values(obs, anchor_scale=1.40)[0]
    assert cluster.coordinated is True


def test_not_coordinated_when_purpose_built_present():
    obs = [_o(1.50, "forum", 0.3, "a"), _o(1.50, "forum", 0.3, "b"),
           _o(1.50, "earningswhispers", 0.85, "c")]
    cluster = cluster_values(obs, anchor_scale=1.40)[0]
    assert cluster.coordinated is False


def test_refine_inliers_rejects_mad_outlier():
    members = (_o(1.40, "earningswhispers", 1.0, "a"), _o(1.41, "estimize", 1.0, "b"),
               _o(1.42, "websearch", 1.0, "c"), _o(1.50, "forum", 1.0, "d"))
    cluster = WhisperCluster(value=1.41, members=members, n_distinct_families=4,
                             support_mass=4.0, weighted_dispersion=0.0)
    center, inliers, n_out, disp, n_fam = refine_inliers(cluster, anchor_scale=1.40)
    vals = sorted(m.value for m in inliers)
    assert 1.50 not in vals and n_out == 1          # the 1.50 edge is trimmed
    assert vals == [1.40, 1.41, 1.42] and n_fam == 3
