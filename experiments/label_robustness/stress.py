"""Fictional label stress corpus, grouped by specimen (private, never committed).

    stress.py OUT [--specimens 30] [--seed 5150]

Each specimen is one device-label sticker (`bench/data/gen_barcodes.py`'s
`labelled_sticker`: random, obviously fictional IMEIs, serials and EANs; the
DEV generator's own value rules), photographed four ways:

    clean        DejaVu Sans (the DEV font), upright +-3 deg, tilt <= 8 deg,
                 blur 0.5-0.8 px, JPEG 85-95: the specimen's control
    font         the same values set in another installed font, cycled by
                 specimen: Liberation Sans, Liberation Serif, DejaVu Sans Mono,
                 Liberation Mono (DEV uses DejaVu Sans only); camera as clean
    blur         DejaVu Sans, gaussian blur 1.6-2.2 px and JPEG 50-70 (DEV's
                 labelled frames stop at 1.5 px)
    perspective  DejaVu Sans, one axis tilted 28-38 deg (DEV's labelled frames
                 stop at 25), in-plane +-8 deg, blur as clean

Frame sizes cycle by specimen: 1280x720, 1920x1080, 720x1280 (the app hands
the label reader at most 1920-wide photos). The content generator is seeded
`[seed, specimen]`, so every condition prints identical values (asserted);
each condition's camera is seeded `[seed, specimen, condition]`. The seed
(5150) is neither DEV's (101) nor TEST's (202); no TEST or reserved frame is
read. Gold is what is printed (`fields`, as gen_barcodes writes them) and the
codes' decodability as gen_barcodes computes it.

Writes OUT/frames/*.jpg, OUT/truth.jsonl and OUT/gold-receipt.json (sha256
of every frame and of truth.jsonl), then makes all of it read-only: the gold
is frozen before any reader sees a frame. Refuses if OUT exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "bench" / "data"))
import cv2  # noqa: E402
import gen_barcodes as gen  # noqa: E402
import numpy as np  # noqa: E402

cv2.setNumThreads(1)
FONTS = "/usr/share/fonts/truetype"
ALT_FONTS = [("liberation/LiberationSans-Regular.ttf", "liberation/LiberationSans-Bold.ttf"),
             ("liberation/LiberationSerif-Regular.ttf", "liberation/LiberationSerif-Bold.ttf"),
             ("dejavu/DejaVuSansMono.ttf", "dejavu/DejaVuSansMono-Bold.ttf"),
             ("liberation/LiberationMono-Regular.ttf", "liberation/LiberationMono-Bold.ttf")]
DEV_FONT = (gen.FONT, gen.FONT_BOLD)
SIZES = [(1280, 720), (1920, 1080), (720, 1280)]
CONDITIONS = ["clean", "font", "blur", "perspective"]


def sticker(seed: int, s: int, fonts: tuple[str, str], frame: tuple[int, int]):
    gen.FONT, gen.FONT_BOLD = fonts
    rng = np.random.default_rng([seed, s])
    fw, _ = frame
    em_f = float(rng.uniform(20, 26)) * max(1.0, fw / 1280)
    m_lo, m_hi = 1.6, 2.8  # gen_barcodes' medium tier
    ctx = {"module_range": (m_lo * max(1.0, fw / 1280), m_hi * max(1.0, fw / 1280)), "landscape": frame[0] > frame[1]}
    n = int(rng.integers(3, 6))
    sheet = gen.labelled_sticker(rng, em_f * gen.K, n, ctx, title=bool(rng.random() < 0.7))
    gen.FONT, gen.FONT_BOLD = DEV_FONT
    return sheet, em_f


def frame_of(seed: int, s: int, ci: int, cond: str, sheet, frame: tuple[int, int]):
    rng = np.random.default_rng([seed, s, ci])
    fw, fh = frame
    bg, bg_kind = gen.augment.background(rng, fw, fh)
    img = bg.astype(np.float32)
    h, w = sheet.image.shape[:2]
    rz = float(rng.uniform(-8, 8)) if cond == "perspective" else float(rng.uniform(-3, 3))
    if cond == "perspective":
        t = float(rng.uniform(28, 38)) * float(rng.choice([-1, 1]))
        rx, ry = (t, float(rng.uniform(-5, 5))) if rng.random() < 0.5 else (float(rng.uniform(-5, 5)), t)
    else:
        rx, ry = float(rng.uniform(-8, 8)), float(rng.uniform(-8, 8))
    shrink, corners = 1.0, None
    while shrink > 0.3 and corners is None:
        for _ in range(30):
            pose = {"rx": rx, "ry": ry, "rz": rz, "width_frac": shrink * w / gen.K / fw,
                    "cx": float(rng.uniform(0.35, 0.65)), "cy": float(rng.uniform(0.35, 0.65))}
            c = gen.augment.project_corners(w, h, frame_w=fw, frame_h=fh, **pose)
            if c[:, 0].min() >= 0.01 * fw and c[:, 0].max() <= 0.99 * fw and c[:, 1].min() >= 0.01 * fh and c[:, 1].max() <= 0.99 * fh:
                corners = c
                break
        shrink *= 0.9
    if corners is None:
        raise RuntimeError(f"specimen {s} {cond}: sticker does not fit")
    img = gen.augment.composite(img, sheet.image, corners)
    H = gen.sheet_homography(w, h, corners)
    if rng.random() < 0.5:
        img = gen.augment.uneven_lighting(img, rng, float(rng.uniform(0.15, 0.3)))
    blur = float(rng.uniform(1.6, 2.2)) if cond == "blur" else float(rng.uniform(0.5, 0.8))
    noise = float(rng.uniform(2, 5))
    out = gen.augment.finish(img, rng, blur, noise)
    q = int(rng.integers(50, 71)) if cond == "blur" else int(rng.integers(85, 96))
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, q])
    assert ok
    codes = []
    for code, origin in sheet.codes:
        mod = gen.module_in_frame(H, code, origin)
        fc = gen.apply_h(H, code.corners + origin)
        codes.append({"format": code.sym.fmt, "text": code.sym.text, "corners": [[round(float(x), 1), round(float(y), 1)] for x, y in fc],
                      "module_px": round(mod, 2), "decodable": bool(code.printed_decodable and mod >= gen.MIN_DECODABLE_MODULE)})
    fields = []
    for f in sheet.fields:
        f = dict(f)
        if "_code" in f:
            f["barcode_decodable"] = codes[f.pop("_code")]["decodable"]
        fields.append(f)
    params = {"rx": round(rx, 1), "ry": round(ry, 1), "rz": round(rz, 1), "blur_sigma": round(blur, 2), "noise_sigma": round(noise, 2),
              "jpeg_quality": q, "background": bg_kind, "shrink": round(shrink / 0.9, 3)}
    return buf.tobytes(), codes, fields, params


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--specimens", type=int, default=30)
    ap.add_argument("--seed", type=int, default=5150)
    a = ap.parse_args()
    if a.seed in gen.SEEDS.values():
        raise SystemExit("seed is a DEV/TEST split seed")
    os.umask(0o077)
    if a.out.exists():
        raise SystemExit(f"{a.out} exists: the corpus is immutable")
    (a.out / "frames").mkdir(parents=True)
    truths = []
    for s in range(a.specimens):
        frame = SIZES[s % len(SIZES)]
        values = None
        for ci, cond in enumerate(CONDITIONS):
            fonts = tuple(f"{FONTS}/{p}" for p in ALT_FONTS[s % len(ALT_FONTS)]) if cond == "font" else DEV_FONT
            sheet, em = sticker(a.seed, s, fonts, frame)
            data, codes, fields, params = frame_of(a.seed, s, ci, cond, sheet, frame)
            got = [(f["label"], f["value"]) for f in fields]
            assert values is None or got == values, "conditions must print identical values"
            values = got
            fid = f"lr_stress_{s:03d}_{cond}"
            rel = f"frames/{fid}.jpg"
            (a.out / rel).write_bytes(data)
            truths.append({"id": fid, "specimen": s, "condition": cond, "image": rel, "size": list(frame),
                           "font": os.path.basename(fonts[0]), "text_em_px": round(em, 1), "params": params, "codes": codes, "fields": fields})
    with open(a.out / "truth.jsonl", "x") as fh:
        for t in truths:
            fh.write(json.dumps(t, sort_keys=True) + "\n")
    rec = {"seed": a.seed, "specimens": a.specimens, "conditions": CONDITIONS, "frames": len(truths),
           "generator": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "gen_barcodes": hashlib.sha256((REPO / "bench/data/gen_barcodes.py").read_bytes()).hexdigest(),
           "truth": hashlib.sha256((a.out / "truth.jsonl").read_bytes()).hexdigest(),
           "files": {t["image"]: hashlib.sha256((a.out / t["image"]).read_bytes()).hexdigest() for t in truths}}
    with open(a.out / "gold-receipt.json", "x") as fh:
        fh.write(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    for p in list((a.out / "frames").iterdir()) + [a.out / "truth.jsonl", a.out / "gold-receipt.json"]:
        p.chmod(0o400)
    (a.out / "frames").chmod(0o500)
    n_fields = sum(len(t["fields"]) for t in truths)
    print(f"wrote {len(truths)} frames ({a.specimens} specimens x {len(CONDITIONS)}), {n_fields} truth fields, gold frozen")


if __name__ == "__main__":
    main()
