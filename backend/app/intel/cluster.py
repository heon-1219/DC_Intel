"""Greedy incremental clustering primitives (market-intel-pipeline.md §5.2). Pure decision
functions over embedding vectors; the Redis-backed cluster store + scraper wiring layer on top."""
import uuid

from app.intel.config import INTEL_SIM_JOIN, INTEL_SIM_NEARDUP
from app.intel.embed import cosine


def new_cluster_id() -> str:
    return "cl_" + uuid.uuid4().hex[:12]


def best_cluster(vec: list[float], clusters: list[dict],
                 threshold: float = INTEL_SIM_JOIN) -> tuple[str | None, float]:
    """Pick the most-similar candidate cluster. clusters = [{cluster_id, centroid}, ...].
    Returns (cluster_id, sim) if best sim >= threshold, else (None, best_sim)."""
    best_id, best_sim = None, -1.0
    for c in clusters:
        s = cosine(vec, c["centroid"])
        if s > best_sim:
            best_sim, best_id = s, c["cluster_id"]
    return (best_id if best_sim >= threshold else None), best_sim


def update_centroid(centroid: list[float], count: int, vec: list[float]) -> list[float]:
    """Running-mean centroid, renormalized to unit length."""
    merged = [(c * count + v) / (count + 1) for c, v in zip(centroid, vec)]
    norm = sum(x * x for x in merged) ** 0.5
    return [x / norm for x in merged] if norm else merged


def is_near_duplicate(vec: list[float], recent_vecs: list[list[float]],
                      threshold: float = INTEL_SIM_NEARDUP) -> bool:
    """Same-author near-dup: cosine >= 0.97 against the author's recent items (§4.3)."""
    return any(cosine(vec, r) >= threshold for r in recent_vecs)
