"""Turn the clean proof-of-address pages into phone-camera photos.

For every <id>.png in --synth (poa_synth.py output) this writes --per-doc K
photos to --out: <id>_cam<k>.jpg (JPEG q88) and <id>_cam<k>.json with the
absolute image and source-truth paths, the frame size, the four page corners
in the photo (TL, TR, BR, BL), the pose and the defects applied. The corners
map the page's span boxes into the photo with one homography.

The phone is held the way the page is: a 1080x1920 portrait frame for A4
portrait pages, 1920x1080 for the A5 landscape slip. The page fills a lot of
the frame: seen face-on it spans 0.80-0.94 of the frame along its binding
dimension (the width for A4 in a portrait frame; for the landscape slip, whose
height binds first, the height), tilted within +-10 deg about x and y and
+-8 deg in-plane, resampled until the whole page is inside the frame with a
small margin. Then a wood or desk background (augment.background), uneven
lighting, one mild glare blob (peak 30-70), gaussian blur 0.3-0.9 and sensor
noise 2-5.

Every photo has its own RNG seeded from (--seed, document number, k), so the
output does not depend on --jobs or on which other documents are present.

Run: .venv/bin/python poa_augment.py [--synth /tmp/docscan-poa/synth] [--out /tmp/docscan-poa/camera]
     [--per-doc 2] [--seed 5] [--jobs 8]
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import time
from pathlib import Path

import cv2
import numpy as np

from augment import background, composite, finish, glare, map_point, project_corners, uneven_lighting

MARGIN = 0.015  # of the frame, on every side


def frame_for(doc_w: int, doc_h: int) -> tuple[int, int]:
    return (1080, 1920) if doc_h > doc_w else (1920, 1080)


def random_pose(rng: np.random.Generator, doc_w: int, doc_h: int, frame: tuple[int, int]) -> tuple[dict, float]:
    """A pose with the whole page in frame; returns (pose, fill along the binding dimension)."""
    fw, fh = frame
    # width_frac that makes the page exactly fill the frame along its binding dimension, face-on
    binding = min(1.0, (fh / fw) / (doc_h / doc_w))
    for _ in range(1000):
        fill = float(rng.uniform(0.80, 0.94))
        pose = {"rx": float(rng.uniform(-10, 10)), "ry": float(rng.uniform(-10, 10)), "rz": float(rng.uniform(-8, 8)),
                "width_frac": fill * binding, "cx": float(rng.uniform(0.47, 0.53)), "cy": float(rng.uniform(0.47, 0.53))}
        c = project_corners(doc_w, doc_h, frame_w=fw, frame_h=fh, **pose)
        mx, my = MARGIN * fw, MARGIN * fh
        if c[:, 0].min() >= mx and c[:, 0].max() <= fw - mx and c[:, 1].min() >= my and c[:, 1].max() <= fh - my:
            return pose, fill
    raise RuntimeError("no in-frame pose found")


def photo(doc: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, dict]:
    h, w = doc.shape[:2]
    fw, fh = frame_for(w, h)
    pose, fill = random_pose(rng, w, h, (fw, fh))
    bg, kind = background(rng, fw, fh)
    corners = project_corners(w, h, frame_w=fw, frame_h=fh, **pose)
    img = composite(bg, doc, corners)
    img = uneven_lighting(img, rng)
    at = map_point(corners, w, h, (float(rng.uniform(0.1, 0.9)) * w, float(rng.uniform(0.1, 0.9)) * h))
    peak = float(rng.uniform(30, 70))
    radius = (float(rng.uniform(60, 140)), float(rng.uniform(40, 90)))
    angle = float(rng.uniform(0, math.pi))
    img = glare(img, at, radius, peak, angle)
    blur, noise = float(rng.uniform(0.3, 0.9)), float(rng.uniform(2, 5))
    out = finish(img, rng, blur, noise)
    meta = {
        "frame": [fw, fh], "corners_tl_tr_br_bl": corners.round(1).tolist(),
        "pose": {**{k: round(v, 4) for k, v in pose.items()}, "fill": round(fill, 4)},
        "background": kind, "blur": round(blur, 3), "noise": round(noise, 3),
        "glare": {"centre": [round(at[0], 1), round(at[1], 1)], "radius": [round(r, 1) for r in radius],
                  "peak": round(peak, 1), "angle": round(angle, 3)},
    }
    return out, meta


def run_one(job: tuple) -> int:
    png, out_dir, per_doc, seed = job
    cv2.setNumThreads(1)
    png, out_dir = Path(png), Path(out_dir)
    doc = cv2.imread(str(png), cv2.IMREAD_COLOR)
    num = int("".join(ch for ch in png.stem if ch.isdigit()) or 0)
    for k in range(per_doc):
        rng = np.random.default_rng([seed, num, k])
        img, meta = photo(doc, rng)
        stem = f"{png.stem}_cam{k}"
        jpg = out_dir / f"{stem}.jpg"
        cv2.imwrite(str(jpg), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        meta = {"image": str(jpg.resolve()), "source": str(png.with_suffix(".json").resolve()), **meta}
        (out_dir / f"{stem}.json").write_text(json.dumps(meta, indent=1) + "\n")
    return per_doc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--synth", default="/tmp/docscan-poa/synth")
    ap.add_argument("--out", default="/tmp/docscan-poa/camera")
    ap.add_argument("--per-doc", type=int, default=2)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--jobs", type=int, default=1)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pngs = sorted(p for p in Path(args.synth).glob("*.png") if not p.stem.endswith("_boxes"))
    jobs = [(str(p), str(out), args.per_doc, args.seed) for p in pngs]
    t0 = time.perf_counter()
    if args.jobs > 1:
        with mp.Pool(args.jobs) as pool:
            n = sum(pool.imap_unordered(run_one, jobs, chunksize=4))
    else:
        n = sum(run_one(j) for j in jobs)
    print(f"wrote {n} photos of {len(pngs)} pages to {out} in {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    main()
