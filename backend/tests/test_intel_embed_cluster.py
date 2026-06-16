import fakeredis.aioredis
import pytest

from app.intel.cluster import best_cluster, is_near_duplicate, new_cluster_id, update_centroid
from app.intel.embed import cache_embedding, cosine, get_cached_embedding


def test_cosine():
    assert cosine([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 1]) == 0.0       # zero vector guard


def test_best_cluster_join_vs_new():
    clusters = [{"cluster_id": "cl_a", "centroid": [1.0, 0.0]},
                {"cluster_id": "cl_b", "centroid": [0.0, 1.0]}]
    cid, sim = best_cluster([0.99, 0.14], clusters, threshold=0.80)
    assert cid == "cl_a" and sim > 0.80
    cid2, sim2 = best_cluster([0.7, 0.7], clusters, threshold=0.80)
    assert cid2 is None and sim2 < 0.80   # equidistant -> below join threshold -> new cluster


def test_update_centroid_running_mean_unit_norm():
    c = update_centroid([1.0, 0.0], 1, [0.0, 1.0])
    assert cosine(c, [1.0, 1.0]) == pytest.approx(1.0)        # mean direction is the diagonal
    assert sum(x * x for x in c) == pytest.approx(1.0)        # renormalized


def test_is_near_duplicate():
    assert is_near_duplicate([1.0, 0.0], [[0.999, 0.045]], threshold=0.97) is True
    assert is_near_duplicate([1.0, 0.0], [[0.0, 1.0]], threshold=0.97) is False


def test_new_cluster_id_format():
    cid = new_cluster_id()
    assert cid.startswith("cl_") and len(cid) == 15   # 'cl_' + 12 hex


@pytest.mark.asyncio
async def test_embedding_cache_roundtrip():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    assert await get_cached_embedding(r, 1) is None
    await cache_embedding(r, 1, [0.1, 0.2, 0.3])
    assert await get_cached_embedding(r, 1) == pytest.approx([0.1, 0.2, 0.3])
