"""Passive anti-spoofing (MiniFASNet pair) on CelebA-Spoof, through docscan's
own detection and landmarks (`examples/face antispoof`).

CelebA-Spoof (Zhang et al., ECCV 2020) is for non-commercial research only;
the copy used here is a Hugging Face mirror of the official images with their
live/spoof labels (Ar4ikov/celebA_spoof), evaluated locally and never
redistributed (face/DATASETS.md). The mirror keeps only live/spoof, not the
spoof type, so APCER is reported over all spoof types together.

DEV = two shards of the mirror's `valid` split (drawn from the official train
subjects), TEST = the first eight shards of the official `test` split (other
subjects). The decision threshold and the crop's box scale are chosen on DEV.

  python antispoof.py extract
  python antispoof.py run dev|test [--box-scale 1.0]
  python antispoof.py score
"""
import argparse
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "docscan/target/release/examples/face"
DATA = Path("/tmp/face-data/celeba-spoof")
SPLITS = {"dev": ["valid0.parquet", "valid-00001-of-00009-d8c838aa3d310fb1.parquet"], "test": sorted(p.name for p in DATA.glob("test-*.parquet"))}
PER_SPLIT = {"dev": 3000, "test": 6000}


def extract():
    for split, files in SPLITS.items():
        d = DATA / split
        d.mkdir(exist_ok=True)
        rows = []
        for f in files:
            t = pq.read_table(DATA / f)
            for r in t.to_pylist():
                rows.append((r["Filepath"]["bytes"], r["Class"]))
        # A fixed, seeded subsample (the shards are large; this bounds the run time).
        rng = np.random.default_rng(0 if split == "dev" else 1)
        idx = rng.permutation(len(rows))[: PER_SPLIT[split]]
        labels, paths = [], []
        for k, i in enumerate(idx):
            b, cls = rows[i]
            p = d / f"{k:05d}.jpg"
            if not p.exists():
                Image.open(io.BytesIO(b)).convert("RGB").save(p, quality=95)
            paths.append(str(p))
            labels.append(cls)
        (d / "list.txt").write_text("\n".join(paths) + "\n")
        (d / "labels.json").write_text(json.dumps(labels))
        print(split, len(paths), {c: labels.count(c) for c in set(labels)})


def run(split, box_scale, jobs=8):
    d = DATA / split
    n = sum(1 for _ in open(d / "list.txt"))
    tmp = Path(tempfile.mkdtemp(prefix="fas-"))
    procs = []
    for i in range(jobs):
        cmd = [str(BIN), "--models", "/tmp/face-models", "--box-scale", str(box_scale), "antispoof", str(d / "list.txt"), str(tmp / f"{i}.json"), "--shard", f"{i}/{jobs}"]
        procs.append(subprocess.Popen(cmd, env={**os.environ, "RAYON_NUM_THREADS": "1"}))
    for p in procs:
        assert p.wait() == 0
    out = []
    for i in range(jobs):
        out += json.loads((tmp / f"{i}.json").read_text())
    assert len(out) == n
    (d / f"scores_{box_scale}.json").write_text(json.dumps(out))


def metrics(scores, live, t):
    """APCER: spoofs accepted; BPCER: live rejected (a face not found is a rejection)."""
    acc = scores >= t
    apcer = float(acc[~live].mean())
    bpcer = float((~acc[live]).mean())
    return {"threshold": t, "apcer": apcer, "bpcer": bpcer, "acer": (apcer + bpcer) / 2}


def eer_threshold(scores, live):
    best = (1.0, 0.5)
    for t in np.unique(scores):
        m = metrics(scores, live, t)
        gap = abs(m["apcer"] - m["bpcer"])
        if gap < best[0]:
            best = (gap, t)
    return float(best[1])


def auc(scores, live):
    pos, neg = scores[live], scores[~live]
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty(len(order))
    ranks[order] = np.arange(1, len(order) + 1)
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def load(split, box_scale):
    d = DATA / split
    labels = np.array(json.loads((d / "labels.json").read_text())) == "live"
    s = json.loads((d / f"scores_{box_scale}.json").read_text())
    found = np.array([x["found"] for x in s])
    scores = np.array([x.get("real", -1.0) if x["found"] else -1.0 for x in s])
    return scores, labels, found


def score():
    out = {}
    scales = sorted(float(p.stem.split("_")[1]) for p in (DATA / "dev").glob("scores_*.json"))
    dev = {}
    for k in scales:
        s, y, found = load("dev", k)
        t = eer_threshold(s, y)
        dev[k] = {"auc": auc(s[found], y[found]), "eer_threshold": t, **metrics(s, y, t), "at_0.5": metrics(s, y, 0.5), "no_face": int((~found).sum())}
    best = max(dev, key=lambda k: dev[k]["auc"])
    out["dev"] = dev
    out["chosen_box_scale"] = best
    if (DATA / "test" / f"scores_{best}.json").exists():
        s, y, found = load("test", best)
        t = dev[best]["eer_threshold"]
        out["test"] = {"box_scale": best, "auc": auc(s[found], y[found]), "at_dev_eer_threshold": metrics(s, y, t), "at_0.5": metrics(s, y, 0.5), "test_eer": metrics(s, y, eer_threshold(s, y)), "no_face": int((~found).sum()), "n": int(len(s)), "live": int(y.sum())}
    Path("/tmp/face-data/results/antispoof_celeba.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract", "run", "score"])
    ap.add_argument("split", nargs="?", default="dev")
    ap.add_argument("--box-scale", type=float, default=1.0)
    a = ap.parse_args()
    if a.cmd == "extract":
        extract()
    elif a.cmd == "run":
        run(a.split, a.box_scale)
    else:
        score()
