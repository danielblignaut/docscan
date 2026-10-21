"""Verification metrics shared by the face evals.

- 10-fold accuracy (the LFW protocol): per fold, the threshold that is best on
  the other nine folds is applied to it; mean and standard deviation.
- TAR at a FAR: the threshold that lets through that share of impostor pairs.
- A fixed threshold's FAR and FRR (a threshold chosen on DEV, applied to TEST).
"""
import numpy as np


def cosine(a, b):
    a = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    b = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-12)
    return (a * b).sum(1)


def best_threshold(scores, same):
    cands = np.unique(scores)
    best, best_acc = 0.0, -1
    # Midpoints between sorted scores.
    s = np.sort(cands)
    mids = np.concatenate([[s[0] - 1e-6], (s[1:] + s[:-1]) / 2, [s[-1] + 1e-6]])
    for t in mids:
        acc = ((scores >= t) == same).mean()
        if acc > best_acc:
            best, best_acc = t, acc
    return best, best_acc


def kfold_accuracy(scores, same, folds):
    accs, ths = [], []
    for f in np.unique(folds):
        test = folds == f
        t, _ = best_threshold(scores[~test], same[~test])
        accs.append(((scores[test] >= t) == same[test]).mean())
        ths.append(t)
    return float(np.mean(accs)), float(np.std(accs)), float(np.mean(ths))


def threshold_at_far(scores, same, far):
    imp = np.sort(scores[~same])[::-1]
    k = int(np.floor(far * len(imp)))
    # The threshold passes at most k impostors.
    return float(imp[k] + 1e-6) if k < len(imp) else float(imp[-1])


def tar_at_far(scores, same, far):
    t = threshold_at_far(scores, same, far)
    return float((scores[same] >= t).mean()), t


def rates(scores, same, t):
    far = float((scores[~same] >= t).mean())
    frr = float((scores[same] < t).mean())
    return far, frr


def summary(scores, same, folds=None):
    scores = np.asarray(scores, dtype=np.float64)
    same = np.asarray(same, dtype=bool)
    out = {"pairs": int(len(scores)), "positives": int(same.sum())}
    if folds is not None:
        m, s, t = kfold_accuracy(scores, same, np.asarray(folds))
        out.update(acc=m, acc_std=s, acc_threshold=t)
    for far in (1e-2, 1e-3):
        if far * (~same).sum() >= 1:
            tar, t = tar_at_far(scores, same, far)
            out[f"tar@far={far:g}"] = tar
            out[f"threshold@far={far:g}"] = t
    return out
