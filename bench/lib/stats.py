"""Statistics shared by the suites (to compute a metric) and compare.py (to
judge a difference between two runs).

Every accuracy-type metric is a function of per-item data stored in the
result JSON (a 0/1 outcome per item, or a score and a label per pair), so the
same function computes the metric and its bootstrap. Differences between two
runs on the same items are judged by a **paired** bootstrap: the same
resampled items are scored under A and under B, and the 95% interval of
B - A decides. Resampling is stratified (by label, and by fold for the LFW
protocol), so class counts stay fixed and a FAR-based threshold keeps its
meaning.

Latencies are judged by the median, the IQR and a two-sided Mann-Whitney U
test (normal approximation with tie correction).
"""
from __future__ import annotations

import math

import numpy as np

# --------------------------------------------------------------------------- #
# Face / verification statistics (match face/eval/verification.py)
# --------------------------------------------------------------------------- #


def best_threshold(scores: np.ndarray, same: np.ndarray) -> tuple[float, float]:
    """The threshold (a midpoint between sorted scores) with the best accuracy,
    by one sort and cumulative counts: O(n log n). Ties resolve to the lowest
    such threshold, as the loop in face/eval/verification.py does."""
    order = np.argsort(scores, kind="stable")
    s = scores[order]
    y = same[order].astype(np.int64)
    n = len(s)
    # Cut at position k: items [0, k) predicted negative, [k, n) positive.
    neg_below = np.concatenate([[0], np.cumsum(1 - y)])  # true negatives
    pos_above = y.sum() - np.concatenate([[0], np.cumsum(y)])  # true positives
    acc = (neg_below + pos_above) / n
    # Only cut between distinct values (and at both ends).
    valid = np.ones(n + 1, bool)
    valid[1:n] = s[1:] != s[:-1]
    acc = np.where(valid, acc, -1.0)
    k = int(np.argmax(acc))
    if k == 0:
        t = s[0] - 1e-6
    elif k == n:
        t = s[-1] + 1e-6
    else:
        t = (s[k - 1] + s[k]) / 2
    return float(t), float(acc[k])


def kfold_accuracy(scores, same, folds) -> float:
    """The LFW protocol: each fold scored at the threshold best on the other nine."""
    scores, same, folds = np.asarray(scores, float), np.asarray(same, bool), np.asarray(folds)
    accs = []
    for f in np.unique(folds):
        test = folds == f
        t, _ = best_threshold(scores[~test], same[~test])
        accs.append(((scores[test] >= t) == same[test]).mean())
    return float(np.mean(accs))


def threshold_at_far(scores, same, far: float) -> float:
    imp = np.sort(np.asarray(scores, float)[~np.asarray(same, bool)])[::-1]
    k = int(np.floor(far * len(imp)))
    return float(imp[k] + 1e-6) if k < len(imp) else float(imp[-1])


def tar_at_far(scores, same, far: float) -> float:
    scores, same = np.asarray(scores, float), np.asarray(same, bool)
    t = threshold_at_far(scores, same, far)
    return float((scores[same] >= t).mean())


def tar_at_threshold(scores, same, t: float) -> float:
    scores, same = np.asarray(scores, float), np.asarray(same, bool)
    return float((scores[same] >= t).mean())


def far_at_threshold(scores, same, t: float) -> float:
    scores, same = np.asarray(scores, float), np.asarray(same, bool)
    return float((scores[~same] >= t).mean())


def auc(scores, positive) -> float:
    """Area under the ROC curve (positive = higher score), ties counted half."""
    scores, positive = np.asarray(scores, float), np.asarray(positive, bool)
    n1, n0 = int(positive.sum()), int((~positive).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = _average_ranks(scores)
    return float((ranks[positive].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def apcer_at(scores, live, t: float) -> float:
    """Attacks (not live) accepted at threshold t."""
    scores, live = np.asarray(scores, float), np.asarray(live, bool)
    return float((scores[~live] >= t).mean())


def bpcer_at(scores, live, t: float) -> float:
    """Bona fide (live) rejected at threshold t."""
    scores, live = np.asarray(scores, float), np.asarray(live, bool)
    return float((scores[live] < t).mean())


def acer_at(scores, live, t: float) -> float:
    return (apcer_at(scores, live, t) + bpcer_at(scores, live, t)) / 2


STATS = {
    "kfold_acc": lambda r, p: kfold_accuracy(r["scores"], r["labels"], r["folds"]),
    "tar_at_far": lambda r, p: tar_at_far(r["scores"], r["labels"], p["far"]),
    "tar_at_threshold": lambda r, p: tar_at_threshold(r["scores"], r["labels"], p["threshold"]),
    "far_at_threshold": lambda r, p: far_at_threshold(r["scores"], r["labels"], p["threshold"]),
    "auc": lambda r, p: auc(r["scores"], r["labels"]),
    "apcer_at": lambda r, p: apcer_at(r["scores"], r["labels"], p["threshold"]),
    "bpcer_at": lambda r, p: bpcer_at(r["scores"], r["labels"], p["threshold"]),
    "acer_at": lambda r, p: acer_at(r["scores"], r["labels"], p["threshold"]),
}


def compute_stat(stat: str, raw: dict, params: dict) -> float:
    r = {k: np.asarray(v) for k, v in raw.items()}
    return STATS[stat](r, params or {})


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #


def _strata(raw: dict, keys: tuple[str, ...]) -> np.ndarray:
    n = len(next(iter(raw.values())))
    if not keys:
        return np.zeros(n, np.int64)
    cols = [np.asarray(raw[k]) for k in keys if k in raw]
    if not cols:
        return np.zeros(n, np.int64)
    _, inv = np.unique(np.stack([c.astype(np.int64) for c in cols], 1), axis=0, return_inverse=True)
    return inv.reshape(-1)


def _resample(strata: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    idx = []
    for s in np.unique(strata):
        members = np.flatnonzero(strata == s)
        idx.append(rng.choice(members, len(members), replace=True))
    return np.concatenate(idx)


def strata_keys(stat: str) -> tuple[str, ...]:
    return ("folds", "labels") if stat == "kfold_acc" else ("labels",)


def bootstrap_stat(stat: str, raw: dict, params: dict, b: int = 1000, seed: int = 0) -> tuple[float, float]:
    """95% percentile interval of one run's statistic."""
    r = {k: np.asarray(v) for k, v in raw.items()}
    st = _strata(r, strata_keys(stat))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(b):
        idx = _resample(st, rng)
        vals.append(STATS[stat]({k: v[idx] for k, v in r.items()}, params or {}))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def paired_bootstrap_stat(stat: str, raw_a: dict, raw_b: dict, params_a: dict, params_b: dict, b: int = 1000, seed: int = 0):
    """B - A on the same items: (delta, lo, hi). Labels and folds must agree."""
    a = {k: np.asarray(v) for k, v in raw_a.items()}
    bb = {k: np.asarray(v) for k, v in raw_b.items()}
    st = _strata(a, strata_keys(stat))
    rng = np.random.default_rng(seed)
    d0 = STATS[stat](bb, params_b or {}) - STATS[stat](a, params_a or {})
    ds = []
    for _ in range(b):
        idx = _resample(st, rng)
        ds.append(STATS[stat]({k: v[idx] for k, v in bb.items()}, params_b or {}) - STATS[stat]({k: v[idx] for k, v in a.items()}, params_a or {}))
    return float(d0), float(np.percentile(ds, 2.5)), float(np.percentile(ds, 97.5))


def bootstrap_rate(ok, b: int = 2000, seed: int = 0) -> tuple[float, float]:
    ok = np.asarray(ok, float)
    if len(ok) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = ok[rng.integers(0, len(ok), size=(b, len(ok)))].mean(1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paired_bootstrap_rate(ok_a, ok_b, b: int = 2000, seed: int = 0):
    """Mean(B) - mean(A) over the same items: (delta, lo, hi)."""
    a, bb = np.asarray(ok_a, float), np.asarray(ok_b, float)
    d = bb - a
    if len(d) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = d[rng.integers(0, len(d), size=(b, len(d)))].mean(1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def unpaired_bootstrap_rate(ok_a, ok_b, b: int = 2000, seed: int = 0):
    a, bb = np.asarray(ok_a, float), np.asarray(ok_b, float)
    rng = np.random.default_rng(seed)
    ma = a[rng.integers(0, len(a), size=(b, len(a)))].mean(1)
    mb = bb[rng.integers(0, len(bb), size=(b, len(bb)))].mean(1)
    d = mb - ma
    return float(bb.mean() - a.mean()), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


# --------------------------------------------------------------------------- #
# Latency
# --------------------------------------------------------------------------- #


def _average_ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), float)
    xs = x[order]
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def mann_whitney(x, y) -> tuple[float, float]:
    """Two-sided Mann-Whitney U test: (U of y over x, p). Normal approximation
    with tie correction (fine for n >= 8 per side; below that p is rough)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n1, n2 = len(x), len(y)
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan")
    allv = np.concatenate([x, y])
    r = _average_ranks(allv)
    r2 = r[n1:].sum()
    u2 = r2 - n2 * (n2 + 1) / 2
    mu = n1 * n2 / 2
    _, counts = np.unique(allv, return_counts=True)
    n = n1 + n2
    tie = (counts**3 - counts).sum() / (n * (n - 1)) if n > 1 else 0
    sigma = math.sqrt(n1 * n2 / 12 * ((n + 1) - tie))
    if sigma == 0:
        return float(u2), 1.0
    z = (u2 - mu - 0.5 * np.sign(u2 - mu)) / sigma
    p = math.erfc(abs(z) / math.sqrt(2))
    return float(u2), float(p)


def median_iqr(x) -> tuple[float, float, float]:
    x = np.asarray(x, float)
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    q1, m, q3 = np.percentile(x, [25, 50, 75])
    return float(m), float(q1), float(q3)


def paired_latency_ratio(x, y, b: int = 2000, seed: int = 0):
    """For latencies of the same items: median of per-item ratios y/x, with a
    bootstrap 95% interval (robust to the load drifting between items)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    r = y / np.maximum(x, 1e-9)
    rng = np.random.default_rng(seed)
    meds = np.median(r[rng.integers(0, len(r), size=(b, len(r)))], axis=1)
    return float(np.median(r)), float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))
