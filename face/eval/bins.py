"""Unpacks an InsightFace evaluation .bin (lfw.bin, calfw.bin, cplfw.bin: a
pickle of (JPEG bytes list, issame list), 112 x 112 ArcFace-aligned crops in
consecutive pairs, 10 folds of equal size) into PNGs and a pairs list.

Usage: python bins.py /tmp/face-data/bins/lfw.bin /tmp/face-data/bins/lfw
Writes OUT/images/NNNNN.png, OUT/list.txt (one path per line, pair i is lines
2i and 2i+1) and OUT/pairs.json (is_same, fold).
"""
import io
import json
import pickle
import sys
from pathlib import Path

from PIL import Image

src, out = sys.argv[1], Path(sys.argv[2])
(out / "images").mkdir(parents=True, exist_ok=True)
with open(src, "rb") as f:
    bins, issame = pickle.load(f, encoding="bytes")
paths = []
for i, b in enumerate(bins):
    p = out / "images" / f"{i:05d}.png"
    if not p.exists():
        Image.open(io.BytesIO(b)).convert("RGB").save(p)
    paths.append(str(p))
n = len(issame)
folds = [i * 10 // n for i in range(n)]
(out / "list.txt").write_text("\n".join(paths) + "\n")
(out / "pairs.json").write_text(json.dumps({"is_same": [bool(x) for x in issame], "fold": folds}))
print(out, len(paths), n)
