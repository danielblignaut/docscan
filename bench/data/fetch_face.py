"""Builds the face sets from downloaded public data (called by prepare.py,
which downloads the pinned files first).

  fetch_face.py lfw              # images/<index>.jpg, pairs_dev.json, pairs_test.json (+ names.json, local only)
  fetch_face.py docpairs dev|test
  fetch_face.py celeba dev|test

LFW: the images are the original JPEG bytes from logasja/lfw's parquet,
numbered in sorted-name order. View 2 (marcelohaps/lfw pairs.csv) is TEST;
View 1 (logasja/lfw pairs/*.parquet: pairsDevTrain + pairsDevTest, matched by
the image paths they carry) minus every pair that also occurs in View 2 is
DEV, as face/eval/recognition.py defines them. Pairs are stored by index:
[a, b, same] (DEV) and [a, b, same, fold] (TEST).

docpairs: face/eval/document.py's render_doc, unchanged, on each pair's first
image, with the documents from the bench's own copy of testdata/synth.

celeba: face/eval/antispoof.py's extract: a fixed seeded sample (DEV seed 0,
3 000 of the first two valid shards; TEST seed 1, 6 000 of the first eight
test shards), saved as JPEG q95.
"""
from __future__ import annotations

import io
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__import__("os").environ.get("BENCH_DATA", "/tmp/docscan-bench"))


def lfw():
    import pandas as pd
    import pyarrow.parquet as pq

    raw = DATA / "raw" / "lfw"
    out = DATA / "face" / "lfw"
    (out / "images").mkdir(parents=True, exist_ok=True)
    rows = pq.read_table(raw / "logasja/data/train-00000-of-00001.parquet").to_pylist()
    by_name = {r["image"]["path"]: r["image"]["bytes"] for r in rows}
    names = sorted(by_name)
    index = {n: i for i, n in enumerate(names)}
    for n, i in index.items():
        p = out / "images" / f"{i:05d}.jpg"
        if not p.exists() or p.stat().st_size != len(by_name[n]):
            p.write_bytes(by_name[n])
    v2 = pd.read_csv(raw / "marcelohaps/pairs.csv")
    test = [[index[a], index[b], int(s), int(f)] for a, b, s, f in zip(v2.image_a, v2.image_b, v2.is_same, v2.fold_id)]
    v1 = []
    for f in ("test", "train"):  # pairsDevTrain (2 200) and pairsDevTest (1 000)
        for r in pq.read_table(raw / f"logasja/pairs/{f}-00000-of-00001.parquet").to_pylist():
            v1.append([index[r["img_0"]["path"]], index[r["img_1"]["path"]], int(r["pair"])])
    in_v2 = {frozenset((a, b)) for a, b, *_ in test}
    dev = [p for p in v1 if frozenset(p[:2]) not in in_v2]
    (out / "pairs_dev.json").write_text(json.dumps(dev))
    (out / "pairs_test.json").write_text(json.dumps(test))
    (out / "names.json").write_text(json.dumps(names))
    print(f"lfw: {len(names)} images, DEV {len(dev)} pairs (View 1 {len(v1)} minus overlap), TEST {len(test)} pairs")


def _render(args):
    sys.path.insert(0, str(ROOT / "face" / "eval"))
    import document as D

    synth = DATA / "id" / "stills" / "synth"
    D.DOCS = {"smart_id": (synth / "za_smart_id_front.png", (1080, 220, 1500, 760), True),
              "passport": (synth / "za_passport.png", (60, 150, 480, 690), False)}
    face, out, seed = args
    return D.render_doc(face, Path(out), seed)


def docpairs(split: str):
    lfwd = DATA / "face" / "lfw"
    pairs = json.loads((lfwd / f"pairs_{split}.json").read_text())
    out = DATA / "face" / f"docpairs_{split}"
    out.mkdir(parents=True, exist_ok=True)
    tasks = [(str(lfwd / "images" / f"{p[0]:05d}.jpg"), str(out / f"{i:05d}.jpg"), i + (0 if split == "dev" else 100000)) for i, p in enumerate(pairs)]
    with ProcessPoolExecutor(8) as ex:
        kinds = list(ex.map(_render, tasks, chunksize=32))
    (out / "pairs.json").write_text(json.dumps([{"doc": f"{i:05d}.jpg", "live": p[1], "same": p[2], "kind": k, **({"fold": p[3]} if len(p) > 3 else {})}
                                                for i, (p, k) in enumerate(zip(pairs, kinds))]))
    print(f"docpairs {split}: {len(tasks)}")


def celeba(split: str):
    import pyarrow.parquet as pq
    from PIL import Image

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from prepare import CELEBA_FILES

    raw = DATA / "raw" / "celeba"
    out = DATA / "face" / f"celeba_{split}"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in CELEBA_FILES[split]:
        for r in pq.read_table(raw / f).to_pylist():
            rows.append((r["Filepath"]["bytes"], r["Class"]))
    rng = np.random.default_rng(0 if split == "dev" else 1)
    idx = rng.permutation(len(rows))[: {"dev": 3000, "test": 6000}[split]]
    labels = []
    for k, i in enumerate(idx):
        b, cls = rows[i]
        p = out / f"{k:05d}.jpg"
        if not p.exists():
            Image.open(io.BytesIO(b)).convert("RGB").save(p, quality=95)
        labels.append(cls)
    (out / "labels.json").write_text(json.dumps(labels))
    print(f"celeba {split}: {len(labels)} ({labels.count('live')} live)")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "lfw":
        lfw()
    elif cmd == "docpairs":
        docpairs(sys.argv[2])
    elif cmd == "celeba":
        celeba(sys.argv[2])
    else:
        raise SystemExit(__doc__)
