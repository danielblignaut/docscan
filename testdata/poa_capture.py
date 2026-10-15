"""Captures of proof-of-address pages: a short burst of camera frames per
document, as the live capture sees while the page is held up.

Each capture has one base pose, background, lighting and glare (drawn as
poa_augment.py draws a single photo), and every frame of it moves a little
from there: up to 1.5 deg of tilt about x and y and 1 deg in-plane, 2% of
scale and 1% of position, a shifted and re-sized glare, re-drawn noise, and
its own focus (a gaussian blur of the capture's base +-0.25), with a 15%
chance of a little motion blur. The live pipeline then picks frames from the
burst (eval/poa_capture_eval.py).

For each document <id> this writes <out>/<id>_f<k>.jpg (JPEG q88) and one
<out>/<id>.json: {"id", "source" (truth path), "frames": [{"image", "frame",
"corners_tl_tr_br_bl", "pose", "blur", "motion"}...]}. Every capture has its
own RNG seeded from (--seed, document number), so it does not depend on
--jobs or on which other documents are present.

  .venv/bin/python poa_capture.py --docs /tmp/docscan-poa/synth --ids @/tmp/docscan-poa/dev/ids.txt \
      --out /tmp/docscan-poa/dev/frames --seed 4242
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

from augment import background, composite, finish, glare, map_point, motion_blur, project_corners, uneven_lighting
from poa_augment import MARGIN, frame_for, random_pose


def in_frame(c, fw, fh) -> bool:
    mx, my = MARGIN * fw, MARGIN * fh
    return c[:, 0].min() >= mx and c[:, 0].max() <= fw - mx and c[:, 1].min() >= my and c[:, 1].max() <= fh - my


def capture(doc: np.ndarray, rng: np.random.Generator, n: int) -> list[tuple[np.ndarray, dict]]:
    h, w = doc.shape[:2]
    fw, fh = frame_for(w, h)
    base, fill = random_pose(rng, w, h, (fw, fh))
    bg, kind = background(rng, fw, fh)
    light_seed = int(rng.integers(1 << 31))
    g_at = (float(rng.uniform(0.1, 0.9)) * w, float(rng.uniform(0.1, 0.9)) * h)
    g_peak = float(rng.uniform(30, 70))
    g_rad = (float(rng.uniform(60, 140)), float(rng.uniform(40, 90)))
    g_ang = float(rng.uniform(0, math.pi))
    blur0 = float(rng.uniform(0.3, 0.9))
    out = []
    for k in range(n):
        for _ in range(200):
            pose = {**base, "rx": base["rx"] + float(rng.uniform(-1.5, 1.5)), "ry": base["ry"] + float(rng.uniform(-1.5, 1.5)),
                    "rz": base["rz"] + float(rng.uniform(-1, 1)), "width_frac": base["width_frac"] * float(rng.uniform(0.98, 1.02)),
                    "cx": base["cx"] + float(rng.uniform(-0.01, 0.01)), "cy": base["cy"] + float(rng.uniform(-0.01, 0.01))}
            corners = project_corners(w, h, frame_w=fw, frame_h=fh, **pose)
            if in_frame(corners, fw, fh):
                break
        else:
            pose, corners = base, project_corners(w, h, frame_w=fw, frame_h=fh, **base)
        img = composite(bg, doc, corners)
        img = uneven_lighting(img, np.random.default_rng(light_seed))  # the same light, frame to frame
        at = map_point(corners, w, h, (g_at[0] + float(rng.uniform(-40, 40)), g_at[1] + float(rng.uniform(-40, 40))))
        img = glare(img, at, (g_rad[0] * float(rng.uniform(0.9, 1.1)), g_rad[1] * float(rng.uniform(0.9, 1.1))),
                    g_peak * float(rng.uniform(0.85, 1.15)), g_ang)
        blur = max(0.2, blur0 + float(rng.uniform(-0.25, 0.25)))
        motion = None
        if rng.random() < 0.15:
            motion = (int(rng.integers(3, 7)), float(rng.uniform(0, 180)))
            img = motion_blur(np.clip(img, 0, 255).astype(np.float32), *motion)
        img = finish(img, rng, blur, float(rng.uniform(2, 5)))
        meta = {"frame": [fw, fh], "corners_tl_tr_br_bl": corners.round(1).tolist(),
                "pose": {**{kk: round(v, 4) for kk, v in pose.items()}, "fill": round(fill, 4)}, "background": kind,
                "blur": round(blur, 3), "motion": motion}
        out.append((img, meta))
    return out


def run_one(job: tuple) -> str:
    png, out_dir, n, seed = job
    cv2.setNumThreads(1)
    png, out_dir = Path(png), Path(out_dir)
    doc = cv2.imread(str(png), cv2.IMREAD_COLOR)
    num = int("".join(ch for ch in png.stem if ch.isdigit()) or 0)
    rng = np.random.default_rng([seed, num])
    frames = []
    for k, (img, meta) in enumerate(capture(doc, rng, n)):
        jpg = out_dir / f"{png.stem}_f{k}.jpg"
        cv2.imwrite(str(jpg), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        frames.append({"image": str(jpg.resolve()), **meta})
    rec = {"id": png.stem, "source": str(png.with_suffix(".json").resolve()), "frames": frames}
    (out_dir / f"{png.stem}.json").write_text(json.dumps(rec, indent=1) + "\n")
    return png.stem


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--docs", required=True)
    ap.add_argument("--ids", help="ids, or @file with one per line (default: every page in --docs)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    docs = Path(args.docs)
    if args.ids:
        ids = Path(args.ids[1:]).read_text().split() if args.ids.startswith("@") else args.ids.split(",")
        pngs = [docs / f"{i}.png" for i in ids]
    else:
        pngs = sorted(p for p in docs.glob("*.png") if not p.stem.endswith("_boxes"))
    jobs = [(str(p), str(out), args.frames, args.seed) for p in pngs]
    t0 = time.perf_counter()
    with mp.Pool(args.jobs) as pool:
        done = list(pool.imap_unordered(run_one, jobs, chunksize=2))
    print(f"wrote {len(done)} captures of {args.frames} frames to {out} in {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    main()
