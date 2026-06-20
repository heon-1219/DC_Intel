"""M5b chronological split + walk-forward folds (prediction-model.md §7.3). Pure index math,
NO shuffle (time series) — train=fit, val=hyperparams/calibration/tau, test=gate."""
from app.ml.split import chronological_split, walk_forward_folds


def test_chronological_split_sizes_and_order():
    train, val, test = chronological_split(100)
    assert (len(train), len(val), len(test)) == (70, 15, 15)
    assert train == list(range(0, 70))         # oldest -> newest, contiguous, NO shuffle
    assert val == list(range(70, 85))
    assert test == list(range(85, 100))


def test_chronological_split_partition_is_complete_and_disjoint():
    train, val, test = chronological_split(37)
    allidx = train + val + test
    assert allidx == list(range(37))           # covers everything, in order, no gaps/overlap


def test_walk_forward_four_expanding_folds():
    folds = walk_forward_folds(100, k=4)
    assert len(folds) == 4
    # each fold: train is an expanding prefix, test is the next contiguous block
    assert folds[0] == (list(range(0, 20)), list(range(20, 40)))
    assert folds[3] == (list(range(0, 80)), list(range(80, 100)))   # final fold -> gate slice
    prev_train_len = -1
    for train, test in folds:
        assert train == list(range(0, train[-1] + 1))   # contiguous prefix from 0
        assert set(train).isdisjoint(test)              # no leakage train<->test
        assert min(test) > max(train)                   # test strictly after train (time order)
        assert len(train) > prev_train_len              # expanding
        prev_train_len = len(train)


def test_walk_forward_tests_are_consecutive_and_cover_tail():
    folds = walk_forward_folds(100, k=4)
    tests = [t for _, t in folds]
    assert tests[0][0] == 20                            # first test starts after first block
    for a, b in zip(tests, tests[1:]):
        assert max(a) + 1 == min(b)                     # consecutive, no gap/overlap
    assert max(tests[-1]) == 99                         # last fold reaches the newest sample
