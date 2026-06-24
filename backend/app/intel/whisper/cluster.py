"""Family dedup, agreement clustering, and MAD inlier refinement for the whisper engine. Pure.
Independence is counted by source FAMILY (not raw rows) so forum echoes can't manufacture consensus
(mirrors intel/dedup.py + the subscore_c distinct-author count)."""
from app.intel import whisper_config as cfg
from app.intel.whisper.models import WhisperCluster
from app.intel.whisper.robust import is_inlier, scaled_mad, weighted_median


def _agree_tol(anchor_scale: float) -> float:
    return max(cfg.AGREE_ABS_TOL, cfg.AGREE_REL_TOL * anchor_scale)


def dedup_by_family(kept_obs: list) -> list:
    """Collapse verbatim echoes (same family + rounded value + snippet) to one (highest weight)."""
    best = {}
    for o in kept_obs:
        key = (o.source_family, round(o.value, 2), o.context_snippet.strip()[:80])
        if key not in best or (o.weight or 0.0) > (best[key].weight or 0.0):
            best[key] = o
    return list(best.values())


def _build_cluster(members: list, anchor_scale: float) -> WhisperCluster:
    pairs = [(m.value, (m.weight or 0.0)) for m in members]
    center = weighted_median(pairs)
    smad = scaled_mad(pairs, center)
    families = {m.source_family for m in members}
    coordinated = (
        len(members) >= 3
        and families.isdisjoint(cfg.PURPOSE_BUILT)
        and len({round(m.value, 2) for m in members}) == 1
        and all((m.weight or 0.0) < 0.5 for m in members)
    )
    disp = (smad / anchor_scale) if anchor_scale else 0.0
    return WhisperCluster(value=center, members=tuple(members), n_distinct_families=len(families),
                          support_mass=sum(w for _, w in pairs), weighted_dispersion=disp,
                          coordinated=coordinated)


def cluster_values(kept_obs: list, anchor_scale: float) -> list:
    """Greedy single-linkage clustering by AGREE_TOL; clusters sorted by support_mass desc."""
    obs = dedup_by_family([o for o in kept_obs if o.value is not None])
    if not obs:
        return []
    tol = _agree_tol(anchor_scale)
    ordered = sorted(obs, key=lambda o: o.value)
    groups = [[ordered[0]]]
    for o in ordered[1:]:
        if abs(o.value - groups[-1][-1].value) <= tol:
            groups[-1].append(o)
        else:
            groups.append([o])
    return sorted((_build_cluster(g, anchor_scale) for g in groups),
                  key=lambda c: c.support_mass, reverse=True)


def refine_inliers(cluster: WhisperCluster, anchor_scale: float):
    """MAD outlier rejection within a cluster; recompute the center on the inlier set.
    Returns (center, inliers, n_outliers, inlier_dispersion, n_distinct_families)."""
    pairs = [(m.value, (m.weight or 0.0)) for m in cluster.members]
    center = weighted_median(pairs)
    smad = scaled_mad(pairs, center)
    inliers = [m for m in cluster.members if is_inlier(m.value, center, smad)]
    in_pairs = [(m.value, (m.weight or 0.0)) for m in inliers]
    center2 = weighted_median(in_pairs) if in_pairs else center
    disp = (scaled_mad(in_pairs, center2) / anchor_scale) if anchor_scale else 0.0
    families = {m.source_family for m in inliers}
    return center2, inliers, len(cluster.members) - len(inliers), disp, len(families)
