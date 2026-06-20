"""Chronological splits for time-series model selection (prediction-model.md §7.3).
NO shuffling — samples must stay in time order so validation/test are strictly in the future of
train (the anti-leakage guard at the split level). Operates on sample COUNT; the caller holds the
chronologically-sorted samples and slices them by these index lists."""


def chronological_split(n: int, ratios: tuple[float, float, float] = (0.70, 0.15, 0.15)):
    """Oldest->newest 70/15/15: train (fit), val (hyperparams + calibration + tau_dir), test (gate).
    Returns (train_idx, val_idx, test_idx) as contiguous index lists covering 0..n-1."""
    t1 = int(n * ratios[0])
    t2 = int(n * (ratios[0] + ratios[1]))
    return list(range(0, t1)), list(range(t1, t2)), list(range(t2, n))


def walk_forward_folds(n: int, k: int = 4):
    """k expanding-window folds: split the timeline into k+1 contiguous blocks; fold j trains on
    blocks[0..j] and tests on block[j+1]. The final fold's test slice is the gate slice; train.py
    soft-warns if any fold's directional win rate < 48%. Returns [(train_idx, test_idx), ...]."""
    edges = [round(i * n / (k + 1)) for i in range(k + 2)]
    return [(list(range(0, edges[j + 1])), list(range(edges[j + 1], edges[j + 2])))
            for j in range(k)]
