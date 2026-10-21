"""Which mesh points to align on (docscan/src/face/recognise.rs Alignment),
compared on the LFW DEV split only, with the shipped recogniser.

  python alignment.py [--model sface_int8]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from embed import run  # noqa: E402
from recognition import MODELS  # noqa: E402
from verification import best_threshold, cosine, summary  # noqa: E402

DATA = Path("/tmp/face-data")

ap = argparse.ArgumentParser()
ap.add_argument("--model", default="sface_int8")
ap.add_argument("--variants", nargs="*", default=["iris", "contour", "nose4", "inner-mouth"])
a = ap.parse_args()
dev = json.loads((DATA / "lfw-view1.json").read_text())
images = sorted({p for x in dev for p in x[:2]})
index = {p: i for i, p in enumerate(images)}
lst = DATA / "lfw-dev-images.txt"
lst.write_text("\n".join(images) + "\n")
y = np.array([x[2] for x in dev])
out = {}
for v in a.variants:
    emb, _ = run(str(lst), str(DATA / "emb" / f"align_{v}_{a.model}.npy"), MODELS[a.model], "/tmp/face-models", extra=["--align", v])
    s = cosine(emb[[index[x[0]] for x in dev]], emb[[index[x[1]] for x in dev]])
    r = summary(s, y)
    r["best_acc"] = best_threshold(s, y)[1]
    out[v] = r
    print(v, json.dumps(r))
(DATA / "results" / f"alignment_{a.model}.json").write_text(json.dumps(out, indent=1))
