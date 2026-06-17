"""Redis-backed incremental cluster store (market-intel-pipeline.md §5.2). Per stock bucket,
keeps the set of active cluster ids + each cluster's centroid/meta as JSON (our Redis client is
decode_responses=True). Assigns a new item to the best matching cluster (cosine >= join) or opens
a new one, updating the running-mean centroid + distinct-author set."""
import json

from app.intel.cluster import best_cluster, new_cluster_id, update_centroid
from app.intel.config import INTEL_CLUSTER_TTL_H, INTEL_SIM_JOIN


def _bucket(stock_id) -> str:
    return str(stock_id) if stock_id is not None else "global"


async def get_active_clusters(redis, stock_id) -> list[dict]:
    cids = await redis.smembers(f"intel:clusters:{_bucket(stock_id)}")
    out = []
    for cid in cids:
        raw = await redis.get(f"intel:cluster:{cid}")
        if raw:
            d = json.loads(raw)
            d["cluster_id"] = cid
            out.append(d)
    return out


async def _save(redis, cluster: dict, stock_id, ttl_h: int = INTEL_CLUSTER_TTL_H) -> None:
    cid = cluster["cluster_id"]
    idx = f"intel:clusters:{_bucket(stock_id)}"
    await redis.sadd(idx, cid)
    await redis.expire(idx, ttl_h * 3600)
    body = {k: v for k, v in cluster.items() if k != "cluster_id"}
    await redis.set(f"intel:cluster:{cid}", json.dumps(body), ex=ttl_h * 3600)


async def assign(redis, stock_id, vec: list[float], author_key: str, posted_at: str,
                 *, join: float = INTEL_SIM_JOIN):
    """Join the best active cluster (cosine >= join) or open a new one. Returns
    (cluster_id, distinct_authors, coordinated)."""
    clusters = await get_active_clusters(redis, stock_id)
    cid, _ = best_cluster(vec, [{"cluster_id": c["cluster_id"], "centroid": c["centroid"]}
                                for c in clusters], threshold=join)
    if cid is None:
        cluster = {"cluster_id": new_cluster_id(), "centroid": vec, "stock_id": stock_id,
                   "item_count": 1, "authors": [author_key], "coordinated": False,
                   "first_posted_at": posted_at}
    else:
        cluster = next(c for c in clusters if c["cluster_id"] == cid)
        cluster["centroid"] = update_centroid(cluster["centroid"], cluster["item_count"], vec)
        cluster["item_count"] += 1
        authors = set(cluster.get("authors", []))
        authors.add(author_key)
        cluster["authors"] = sorted(authors)
    await _save(redis, cluster, stock_id)
    return cluster["cluster_id"], len(set(cluster.get("authors", []))), \
        bool(cluster.get("coordinated", False))
