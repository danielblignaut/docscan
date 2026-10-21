"""Runs `examples/face embed` over a list of images in parallel shards and
merges the templates. Usage:
  python embed.py LIST OUT.npy --recogniser FILE:NAME:KIND [--aligned] [--flip] [--jobs 8]
Writes OUT.npy (templates, zeros where no face) and OUT.json (per-image info).
"""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "docscan/target/release/examples/face"


def run(list_path, out, recogniser, models, aligned=False, flip=False, jobs=8, extra=()):
    n = sum(1 for l in open(list_path) if l.strip())
    tmp = Path(tempfile.mkdtemp(prefix="face-embed-"))
    procs = []
    for i in range(jobs):
        cmd = [str(BIN), "--models", models, "--recogniser", recogniser, "embed", list_path, str(tmp / f"{i}.f32"), "--shard", f"{i}/{jobs}"]
        if aligned:
            cmd.append("--aligned")
        if flip:
            cmd.append("--flip")
        cmd += list(extra)
        procs.append(subprocess.Popen(cmd, env={**os.environ, "RAYON_NUM_THREADS": "1"}))
    for p in procs:
        assert p.wait() == 0
    vecs, items, dim = [], [], 0
    for i in range(jobs):
        meta = json.loads((tmp / f"{i}.f32.json").read_text())
        dim = max(dim, meta["dim"])
        items += meta["items"]
    for i in range(jobs):
        meta = json.loads((tmp / f"{i}.f32.json").read_text())
        raw = np.fromfile(tmp / f"{i}.f32", dtype="<f4")
        k = len(meta["items"])
        if k == 0:
            continue
        d = raw.size // k
        v = raw.reshape(k, d)
        if d != dim:
            v = np.zeros((k, dim), np.float32)
        vecs.append(v)
    emb = np.concatenate(vecs)
    assert len(emb) == n, (len(emb), n)
    np.save(out, emb)
    Path(str(out).replace(".npy", "") + ".json").write_text(json.dumps(items))
    return emb, items


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("list")
    ap.add_argument("out")
    ap.add_argument("--recogniser", required=True)
    ap.add_argument("--models", default="/tmp/face-models")
    ap.add_argument("--aligned", action="store_true")
    ap.add_argument("--flip", action="store_true")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    run(a.list, a.out, a.recogniser, a.models, a.aligned, a.flip, a.jobs)
