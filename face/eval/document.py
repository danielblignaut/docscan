"""Document-to-live face matching on LFW pairs, with one side re-rendered as
an identity document's printed photo.

For each LFW pair (a, b): image a's face is cropped to a passport-style
portrait, printed as an ID photo (greyscale and high-contrast as a smart ID
card's laser engraving, or colour as a passport's, desaturated), with a
halftone screen, a holographic overlay of iridescent guilloche lines, and a
glare spot; pasted into the photo box of one of testdata/synth.py's fictional
documents (the SA smart ID front or the SA passport data page); and the
document "captured": downscaled to a phone camera's resolution, blurred,
noised and JPEG-compressed. Image b is the live side, as is.

The document image goes through docscan's own pipeline (`examples/face embed
--largest`: multi-scale detection, landmarks, alignment, template); the live
image through the same pipeline as LFW (the LFW run's templates are reused).

DEV = LFW View 1 (pairs not in View 2), TEST = View 2. Thresholds are chosen
on DEV and applied unchanged to TEST.

  python document.py render            # writes /tmp/face-data/docpairs/{dev,test}/
  python document.py score --model sface_int8
"""
import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from embed import run  # noqa: E402
from recognition import MODELS, lfw_pairs  # noqa: E402
from verification import cosine, rates, summary, threshold_at_far  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = Path("/tmp/face-data")
OUT = DATA / "docpairs"
DOCS = {
    "smart_id": (ROOT / "testdata/synth/za_smart_id_front.png", (1080, 220, 1500, 760), True),
    "passport": (ROOT / "testdata/synth/za_passport.png", (60, 150, 480, 690), False),
}


def portrait(img):
    """LFW's 250 x 250 images centre the face (about 110 px wide): a 3:4
    head-and-shoulders crop."""
    h, w = img.shape[:2]
    cw, ch = int(w * 0.62), int(w * 0.62 * 4 / 3)
    x0 = (w - cw) // 2
    y0 = max(0, (h - ch) // 2 - int(h * 0.02))
    return img[y0 : y0 + ch, x0 : x0 + cw]


def halftone(grey, rng, cell=3):
    """An ordered-dither screen at the print's resolution."""
    bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16
    h, w = grey.shape
    t = np.tile(bayer, (h // 4 + 1, w // 4 + 1))[:h, :w]
    dots = (grey / 255.0 > t).astype(np.float32) * 255
    return cv2.GaussianBlur(dots, (0, 0), 0.9) * 0.55 + grey * 0.45


def hologram(shape, rng):
    """Iridescent guilloche lines and a faint emblem, as an RGBA-ish overlay."""
    h, w = shape
    ov = np.zeros((h, w, 3), np.float32)
    a = np.zeros((h, w), np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    for k in range(rng.integers(3, 7)):
        f = rng.uniform(0.015, 0.05)
        ph = rng.uniform(0, 6.28)
        y0 = rng.uniform(0, h)
        amp = rng.uniform(10, 40)
        d = np.abs(yy - (y0 + amp * np.sin(f * xx + ph)))
        line = np.clip(1.5 - d, 0, 1)
        hue = (xx / w * 180 + k * 30 + rng.uniform(0, 180)) % 180
        hsv = np.stack([hue, np.full_like(hue, 200), np.full_like(hue, 255)], -1).astype(np.uint8)
        col = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(np.float32)
        ov = ov * (1 - line[..., None]) + col * line[..., None]
        a = np.maximum(a, line * rng.uniform(0.25, 0.5))
    # A circular emblem.
    cx, cy, r = rng.uniform(0.2, 0.8) * w, rng.uniform(0.3, 0.8) * h, rng.uniform(0.15, 0.3) * w
    ring = np.clip(2 - np.abs(np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) - r), 0, 1)
    ov = ov * (1 - ring[..., None]) + 230 * ring[..., None]
    a = np.maximum(a, ring * 0.3)
    return ov, a


def glare(shape, rng):
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = rng.uniform(0, w), rng.uniform(0, h)
    sx, sy = rng.uniform(0.1, 0.35) * w, rng.uniform(0.1, 0.3) * h
    return np.exp(-(((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2)) * rng.uniform(0, 140)


def render_doc(face_path: str, out: Path, seed: int):
    rng = np.random.default_rng(seed)
    kind = "smart_id" if seed % 2 == 0 else "passport"
    bg_path, box, grey_print = DOCS[kind]
    doc = cv2.imread(str(bg_path))[:, :, ::-1].astype(np.float32)
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    face = portrait(cv2.imread(face_path)[:, :, ::-1])
    face = cv2.resize(face, (bw, bh), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    if grey_print:
        g = face.mean(2)
        g = np.clip((g - 128) * rng.uniform(1.2, 1.5) + 128 + rng.uniform(-10, 10), 0, 255)
        g = halftone(g, rng)
        face = np.stack([g * 0.95, g * 0.97, g], -1)
    else:
        m = face.mean(2, keepdims=True)
        face = m + (face - m) * rng.uniform(0.6, 0.85)
        face = face * rng.uniform(0.85, 0.95) + rng.uniform(5, 20)
        face = np.stack([halftone(face[..., k], rng) for k in range(3)], -1)
    ov, a = hologram((bh, bw), rng)
    face = face * (1 - a[..., None]) + ov * a[..., None]
    face = face + glare((bh, bw), rng)[..., None]
    doc[y0:y1, x0:x1] = face
    # The capture: a phone camera's view of the card, flattened.
    w = int(rng.uniform(800, 1300))
    doc = cv2.resize(np.clip(doc, 0, 255), (w, int(w * doc.shape[0] / doc.shape[1])), interpolation=cv2.INTER_AREA)
    doc = cv2.GaussianBlur(doc, (0, 0), rng.uniform(0.4, 1.1))
    doc = doc + rng.normal(0, rng.uniform(1.5, 4), doc.shape)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), np.clip(doc, 0, 255).astype(np.uint8)[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, int(rng.uniform(60, 88))])
    return kind


def _render(args):
    return render_doc(*args)


def splits():
    v1, v2 = lfw_pairs()
    return {"dev": v1, "test": v2}


def render(jobs=8):
    for split, pairs in splits().items():
        d = OUT / split
        tasks = [(a, d / f"{i:05d}.jpg", i + (0 if split == "dev" else 100000)) for i, (a, b, *_rest) in enumerate(pairs)]
        with ProcessPoolExecutor(jobs) as ex:
            kinds = list(ex.map(_render, tasks, chunksize=32))
        (d / "list.txt").write_text("\n".join(str(t[1]) for t in tasks) + "\n")
        (d / "kinds.json").write_text(json.dumps(kinds))
        print(split, len(tasks))


def score(model: str, flip: bool):
    res = {}
    lfw_emb = np.load(DATA / "emb" / f"lfw_{model}{'_flip' if flip else ''}.npy")
    images = (DATA / "lfw-images.txt").read_text().split()
    index = {p: i for i, p in enumerate(images)}
    for split, pairs in splits().items():
        d = OUT / split
        emb, items = run(str(d / "list.txt"), str(DATA / "emb" / f"doc{split}_{model}.npy"), MODELS[model], "/tmp/face-models", flip=flip, extra=["--largest"])
        live = lfw_emb[[index[p[1]] for p in pairs]]
        s = cosine(emb, live)
        found = np.array([it["found"] for it in items])
        s[~found] = -1.0  # no face on the document: a rejection
        y = np.array([p[2] for p in pairs])
        kinds = np.array(json.loads((d / "kinds.json").read_text()))
        res[split] = {"all": summary(s, y), "no_face": int((~found).sum())}
        for k in ("smart_id", "passport"):
            m = kinds == k
            res[split][k] = summary(s[m], y[m])
        res[split]["_scores"] = (s, y)
    out = {"model": model, "dev": {k: v for k, v in res["dev"].items() if k != "_scores"}, "test": {k: v for k, v in res["test"].items() if k != "_scores"}}
    sd, yd = res["dev"]["_scores"]
    st, yt = res["test"]["_scores"]
    for far in (1e-2, 1e-3):
        t = threshold_at_far(sd, yd, far)
        fa, fr = rates(st, yt, t)
        out[f"dev_threshold@far={far:g}"] = t
        out[f"test_at_dev_threshold@far={far:g}"] = {"far": fa, "frr": fr, "tar": 1 - fr}
    (DATA / "results" / f"document_{model}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["render", "score"])
    ap.add_argument("--model", default="sface_int8")
    ap.add_argument("--flip", action="store_true")
    a = ap.parse_args()
    if a.cmd == "render":
        render()
    else:
        score(a.model, a.flip)
