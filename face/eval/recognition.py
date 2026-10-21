"""Recognition benchmarks for every candidate model.

  python recognition.py bins   [--models ...]   # lfw.bin, calfw.bin, cplfw.bin: pre-aligned crops
  python recognition.py lfw    [--models ...]   # raw LFW through docscan's own detector,
                                                # landmarks and alignment: DEV = View 1
                                                # (pairsDevTrain + pairsDevTest), TEST = View 2

Results go to /tmp/face-data/results/<set>_<model>[_flip].json and are printed.
The thresholds the demo ships (docscan/src/face/mod.rs THRESHOLDS) are the
DEV thresholds at FAR = 1e-3, applied unchanged to TEST.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from embed import run  # noqa: E402
from verification import cosine, rates, summary, threshold_at_far  # noqa: E402

DATA = Path("/tmp/face-data")
OUT = DATA / "results"
MODELS = {
    "w600k_mbf": "w600k_mbf.onnx:w600k_mbf:arcface",
    "w600k_r50": "buffalo_l/w600k_r50.onnx:w600k_r50:arcface",
    "edgeface_xs": "edgeface_xs_gamma_06.onnx:edgeface_xs:arcface",
    "edgeface_s": "edgeface_s_gamma_05.onnx:edgeface_s:arcface",
    "sface": "sface_nodrop.onnx:sface:sface",
    "facenet": "facenet_vggface2.onnx:facenet:facenet",
    # Weight-only int8 (face/tools/quantise.py: int8 weights, per-channel
    # scales, DequantizeLinear in the graph; float32 arithmetic). This is
    # what the demo ships for SFace.
    "sface_int8": "sface_w8.onnx:sface_int8:sface",
    "w600k_mbf_int8": "w600k_mbf_w8.onnx:w600k_mbf_int8:arcface",
    "edgeface_xs_int8": "edgeface_xs_w8.onnx:edgeface_xs_int8:arcface",
    # onnxruntime quantize_dynamic (ConvInteger/MatMulInteger): diverges on rten 0.26.
    "sface_dynq": "sface_nodrop_int8.onnx:sface_dynq:sface",
    "w600k_mbf_dynq": "w600k_mbf_int8.onnx:w600k_mbf_dynq:arcface",
}


def bins(models, flip):
    for name in models:
        if name == "facenet":
            continue
        for b in ("lfw", "calfw", "cplfw"):
            tag = f"{b}bin_{name}{'_flip' if flip else ''}"
            emb, _ = run(str(DATA / "bins" / b / "list.txt"), str(DATA / "emb" / f"{tag}.npy"), MODELS[name], "/tmp/face-models", aligned=True, flip=flip)
            p = json.loads((DATA / "bins" / b / "pairs.json").read_text())
            s = cosine(emb[0::2], emb[1::2])
            r = summary(s, p["is_same"], p["fold"])
            (OUT / f"{tag}.json").write_text(json.dumps(r, indent=1))
            print(tag, json.dumps(r))


def lfw_pairs():
    """View 2 (pairs.csv: 10 folds) and View 1 (pairsDevTrain/Test)."""
    import pandas as pd

    root = DATA / "lfw-hf"
    v2 = pd.read_csv(root / "pairs.csv")
    v2 = [(str(root / "train" / a), str(root / "train" / b), bool(s), int(f)) for a, b, s, f in zip(v2.image_a_path, v2.image_b_path, v2.is_same, v2.fold_id)]
    v1 = json.loads((DATA / "lfw-view1.json").read_text())
    return v1, v2


def lfw(models, flip):
    v1, v2 = lfw_pairs()
    images = sorted({p for a, b, *_ in v1 + v2 for p in (a, b)})
    index = {p: i for i, p in enumerate(images)}
    lst = DATA / "lfw-images.txt"
    lst.write_text("\n".join(images) + "\n")
    for name in models:
        tag = f"lfw_{name}{'_flip' if flip else ''}"
        emb, items = run(str(lst), str(DATA / "emb" / f"{tag}.npy"), MODELS[name], "/tmp/face-models", flip=flip)
        missing = sum(1 for it in items if not it["found"])

        def score(pairs):
            a = np.array([index[p[0]] for p in pairs])
            b = np.array([index[p[1]] for p in pairs])
            return cosine(emb[a], emb[b]), np.array([p[2] for p in pairs])

        sd, yd = score(v1)
        st, yt = score(v2)
        folds = np.array([p[3] for p in v2])
        t = threshold_at_far(sd, yd, 1e-3)
        far, frr = rates(st, yt, t)
        r = {
            "model": name,
            "flip": flip,
            "images": len(images),
            "no_face": missing,
            "dev": summary(sd, yd),
            "test": summary(st, yt, folds),
            "dev_threshold@far=1e-3": t,
            "test_at_dev_threshold": {"far": far, "frr": frr, "tar": 1 - frr},
        }
        (OUT / f"{tag}.json").write_text(json.dumps(r, indent=1))
        print(tag, json.dumps(r))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("set", choices=["bins", "lfw"])
    ap.add_argument("--models", nargs="*", default=list(MODELS))
    ap.add_argument("--flip", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (DATA / "emb").mkdir(parents=True, exist_ok=True)
    {"bins": bins, "lfw": lfw}[a.set](a.models, a.flip)
