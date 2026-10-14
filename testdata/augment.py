"""Turn the clean synthetic documents into camera-like photos.

For every synth/<name>.png this writes, under camera/:
  <name>_good_<k>.jpg  - document on a wood or desk background, random 3-D tilt
                         (each axis within +-15 deg), scale variation, mild blur,
                         sensor noise, uneven lighting and one glare blob.
  <name>_bad_motion.jpg     - heavy motion blur
  <name>_bad_cropped.jpg    - document about half out of frame
  <name>_bad_glare.jpg      - strong glare over the MRZ (passports) or the barcode
and a <stem>.json beside each with the source truth file, the four document
corners in the output image (TL, TR, BR, BL), the pose and the defects applied.

The scene helpers (backgrounds, pose -> homography, compositing, lighting) are
reused by make_videos.py.

Run: .venv/bin/python augment.py [--per-doc 4] [--seed 7]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
SYNTH = ROOT / "synth"
CAMERA = ROOT / "camera"

# --------------------------------------------------------------------------- #
# Backgrounds
# --------------------------------------------------------------------------- #


def smooth_noise(rng: np.random.Generator, h: int, w: int, scale: int) -> np.ndarray:
    small = rng.random((max(2, h // scale), max(2, w // scale))).astype(np.float32)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def wood_background(rng: np.random.Generator, w: int, h: int) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    warp = smooth_noise(rng, h, w, 120) * 60 + smooth_noise(rng, h, w, 25) * 8
    angle = rng.uniform(-0.3, 0.3)
    u = x * math.cos(angle) + y * math.sin(angle)
    v = -x * math.sin(angle) + y * math.cos(angle)
    rings = np.sin((v + warp) * rng.uniform(0.05, 0.09) + np.sin(u * 0.004) * 3) * 0.5 + 0.5
    grain = smooth_noise(rng, h, w, 3) * 0.25
    t = np.clip(0.55 * rings + 0.3 * grain + 0.15 * smooth_noise(rng, h, w, 200), 0, 1)
    base = np.array(rng.choice([[40, 80, 130], [55, 100, 150], [30, 60, 95]]), np.float32)  # BGR browns
    dark = base * 0.55
    img = dark[None, None, :] * (1 - t[..., None]) + base[None, None, :] * t[..., None]
    # plank seams
    plank = int(rng.integers(160, 260))
    for k in range(-2 * h, 2 * h, plank):
        p1 = (0, int(k))
        p2 = (w, int(k + w * math.tan(angle)))
        cv2.line(img, p1, p2, (18, 30, 45), 2, cv2.LINE_AA)
    return np.clip(img, 0, 255).astype(np.uint8)


def desk_background(rng: np.random.Generator, w: int, h: int) -> np.ndarray:
    base = np.array(rng.choice([[200, 200, 196], [170, 175, 180], [60, 60, 64], [215, 225, 230]]), np.float32)
    tex = (smooth_noise(rng, h, w, 2) - 0.5) * 18 + (smooth_noise(rng, h, w, 150) - 0.5) * 30
    img = np.clip(base[None, None, :] + tex[..., None], 0, 255).astype(np.uint8)
    # clutter: papers, a keyboard-ish block, pens, a mug ring, sticky notes with fake text lines
    for _ in range(int(rng.integers(4, 9))):
        kind = rng.integers(0, 4)
        cx, cy = int(rng.integers(0, w)), int(rng.integers(0, h))
        if kind == 0:  # sheet of paper with text lines
            pw, ph = int(rng.integers(w // 6, w // 3)), int(rng.integers(h // 4, h // 2))
            rect = ((cx, cy), (pw, ph), float(rng.uniform(0, 180)))
            box = cv2.boxPoints(rect).astype(np.int32)
            cv2.fillConvexPoly(img, box, (240, 242, 243), cv2.LINE_AA)
            for j in range(4, 20):
                a = box[0] + (box[3] - box[0]) * (j / 22.0)
                b = a + (box[1] - box[0]) * rng.uniform(0.5, 0.9)
                cv2.line(img, tuple(a.astype(int)), tuple(b.astype(int)), (120, 120, 120), 1, cv2.LINE_AA)
        elif kind == 1:  # pen
            L = int(rng.integers(120, 260))
            ang = rng.uniform(0, math.pi)
            p2 = (int(cx + L * math.cos(ang)), int(cy + L * math.sin(ang)))
            col = tuple(int(c) for c in rng.integers(0, 200, 3))
            cv2.line(img, (cx, cy), p2, col, int(rng.integers(8, 14)), cv2.LINE_AA)
        elif kind == 2:  # mug / coaster ring
            r = int(rng.integers(40, 90))
            cv2.circle(img, (cx, cy), r, tuple(int(c) for c in rng.integers(30, 220, 3)), -1, cv2.LINE_AA)
            cv2.circle(img, (cx, cy), int(r * 0.8), (40, 40, 40), 3, cv2.LINE_AA)
        else:  # sticky note
            s = int(rng.integers(60, 110))
            col = [(120, 230, 250), (180, 240, 160), (230, 180, 250)][int(rng.integers(0, 3))]
            rect = ((cx, cy), (s, s), float(rng.uniform(0, 90)))
            cv2.fillConvexPoly(img, cv2.boxPoints(rect).astype(np.int32), col, cv2.LINE_AA)
    return cv2.GaussianBlur(img, (0, 0), 1.2)


def background(rng: np.random.Generator, w: int, h: int, kind: str | None = None) -> tuple[np.ndarray, str]:
    kind = kind or ("wood" if rng.random() < 0.5 else "desk")
    return (wood_background(rng, w, h) if kind == "wood" else desk_background(rng, w, h)), kind


# --------------------------------------------------------------------------- #
# Pose -> homography
# --------------------------------------------------------------------------- #


def project_corners(doc_w: int, doc_h: int, *, frame_w: int, frame_h: int, width_frac: float,
                    rx: float, ry: float, rz: float, cx: float, cy: float, focal_frac: float = 1.2) -> np.ndarray:
    """Corners (TL, TR, BR, BL) of a doc rotated in 3-D (degrees) and projected by a pinhole camera.

    width_frac: document width as a fraction of frame width when seen face-on.
    cx, cy: where the document centre lands, as fractions of the frame.
    """
    f = focal_frac * frame_w
    half_w = width_frac * frame_w / 2
    half_h = half_w * doc_h / doc_w
    pts = np.array([[-half_w, -half_h, 0], [half_w, -half_h, 0], [half_w, half_h, 0], [-half_w, half_h, 0]], np.float64)
    ax, ay, az = (math.radians(a) for a in (rx, ry, rz))
    Rx = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    Ry = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    Rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    p = pts @ (Rz @ Ry @ Rx).T
    p[:, 2] += f
    u = f * p[:, 0] / p[:, 2] + cx * frame_w
    v = f * p[:, 1] / p[:, 2] + cy * frame_h
    return np.stack([u, v], axis=1).astype(np.float32)


def composite(bg: np.ndarray, doc_bgr: np.ndarray, corners: np.ndarray, shadow: bool = True) -> np.ndarray:
    longest = max(float(np.linalg.norm(corners[i] - corners[(i + 1) % 4])) for i in range(4))
    h0, w0 = doc_bgr.shape[:2]
    shrink = min(1.0, 1.15 * longest / max(w0, h0))
    if shrink < 1.0:
        doc_bgr = cv2.resize(doc_bgr, (round(w0 * shrink), round(h0 * shrink)), interpolation=cv2.INTER_AREA)
    h, w = doc_bgr.shape[:2]
    src = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)
    H = cv2.getPerspectiveTransform(src, corners)
    out_w, out_h = bg.shape[1], bg.shape[0]
    warped = cv2.warpPerspective(doc_bgr, H, (out_w, out_h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    mask = np.zeros((out_h, out_w), np.float32)
    cv2.fillConvexPoly(mask, corners.round().astype(np.int32), 1.0, cv2.LINE_AA)
    # rounded-ish edges / anti-alias
    mask = cv2.GaussianBlur(mask, (0, 0), 0.8)
    img = bg.astype(np.float32)
    if shadow:
        sh = cv2.GaussianBlur(np.roll(mask, (8, 6), axis=(0, 1)), (0, 0), 9)
        img *= (1 - 0.45 * sh)[..., None]
    img = img * (1 - mask[..., None]) + warped.astype(np.float32) * mask[..., None]
    return img


# --------------------------------------------------------------------------- #
# Photometric defects (all on float32 BGR, 0..255)
# --------------------------------------------------------------------------- #


def uneven_lighting(img: np.ndarray, rng: np.random.Generator, strength: float = 0.35) -> np.ndarray:
    h, w = img.shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = rng.uniform(0, 2 * math.pi)
    grad = ((x / w - 0.5) * math.cos(ang) + (y / h - 0.5) * math.sin(ang))
    vign = 1 - 0.35 * (((x / w - 0.5) ** 2 + (y / h - 0.5) ** 2) * 2)
    gain = (1 + strength * grad) * vign * (0.9 + 0.2 * smooth_noise(rng, h, w, 300))
    tint = np.array([rng.uniform(0.92, 1.0), 1.0, rng.uniform(1.0, 1.08)], np.float32)  # warm indoor light
    return img * gain[..., None] * tint


def glare(img: np.ndarray, centre: tuple[float, float], radius: tuple[float, float], peak: float, angle: float = 0) -> np.ndarray:
    h, w = img.shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = x - centre[0], y - centre[1]
    c, s = math.cos(angle), math.sin(angle)
    u, v = (dx * c + dy * s) / radius[0], (-dx * s + dy * c) / radius[1]
    blob = np.exp(-(u * u + v * v) * 2.0)
    core = np.exp(-(u * u + v * v) * 9.0)
    return img + (peak * blob + 0.6 * peak * core)[..., None]


def finish(img: np.ndarray, rng: np.random.Generator, blur_sigma: float, noise_sigma: float) -> np.ndarray:
    if blur_sigma > 0:
        img = cv2.GaussianBlur(img, (0, 0), blur_sigma)
    img = img + rng.normal(0, noise_sigma, img.shape).astype(np.float32)
    return np.clip(img, 0, 255).astype(np.uint8)


def motion_blur(img: np.ndarray, length: int, angle_deg: float) -> np.ndarray:
    k = np.zeros((length, length), np.float32)
    k[length // 2, :] = 1.0
    M = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), angle_deg, 1.0)
    k = cv2.warpAffine(k, M, (length, length))
    k /= k.sum()
    return cv2.filter2D(img, -1, k)


# --------------------------------------------------------------------------- #
# Scene generation
# --------------------------------------------------------------------------- #


def load_doc(name: str) -> tuple[np.ndarray, dict]:
    truth = json.loads((SYNTH / f"{name}.json").read_text())
    return cv2.imread(str(SYNTH / f"{name}.png"), cv2.IMREAD_COLOR), truth


def random_pose(rng: np.random.Generator, portrait: bool, doc_size: tuple[int, int] | None = None,
                frame: tuple[int, int] = (1920, 1080), margin: float = 0.03) -> dict:
    """A random pose; with doc_size given, resampled until the whole document is inside the frame."""
    for _ in range(200):
        pose = _pose(rng, portrait)
        if doc_size is None:
            return pose
        c = project_corners(*doc_size, frame_w=frame[0], frame_h=frame[1], **pose)
        mx, my = margin * frame[0], margin * frame[1]
        if c[:, 0].min() >= mx and c[:, 0].max() <= frame[0] - mx and c[:, 1].min() >= my and c[:, 1].max() <= frame[1] - my:
            return pose
    raise RuntimeError("no in-frame pose found")


def _pose(rng: np.random.Generator, portrait: bool) -> dict:
    return {
        "rx": float(rng.uniform(-15, 15)), "ry": float(rng.uniform(-15, 15)), "rz": float(rng.uniform(-15, 15)),
        "width_frac": float(rng.uniform(0.6, 0.85)),
        "cx": float(rng.uniform(0.42, 0.58)), "cy": float(rng.uniform(0.42, 0.58)),
    }


def region_of_interest(name: str, doc_w: int, doc_h: int) -> tuple[float, float]:
    """Where to put the 'bad glare' blob, in document pixel coordinates."""
    if "passport" in name:
        return doc_w * 0.5, doc_h - 140  # the MRZ band
    if name == "za_smart_id_back":
        return doc_w * 0.68, doc_h * 0.5  # the PDF417
    if name == "za_green_id_book":
        return doc_w * 0.5, 275  # the Code 39
    if name == "multi_barcode":
        return doc_w * 0.5, doc_h * 0.5
    return doc_w * 0.25, doc_h * 0.6  # smart ID front: the identity number


def frame_for(doc: np.ndarray) -> tuple[int, int]:
    """A phone held the way the document is: landscape 1920x1080, or portrait 1080x1920."""
    h, w = doc.shape[:2]
    return (1080, 1920) if h > w else (1920, 1080)


def map_point(corners: np.ndarray, doc_w: int, doc_h: int, pt: tuple[float, float]) -> tuple[float, float]:
    src = np.array([[0, 0], [doc_w - 1, 0], [doc_w - 1, doc_h - 1], [0, doc_h - 1]], np.float32)
    H = cv2.getPerspectiveTransform(src, corners)
    p = cv2.perspectiveTransform(np.array([[pt]], np.float32), H)[0, 0]
    return float(p[0]), float(p[1])


def render(name: str, doc: np.ndarray, rng: np.random.Generator, *, frame=None, pose=None,
           bg_kind=None, blur=None, noise=None, glare_at=None, glare_peak=None, glare_radius=None,
           glare_angle=None, motion=None) -> tuple[np.ndarray, dict]:
    h, w = doc.shape[:2]
    frame = frame or frame_for(doc)
    fw, fh = frame
    pose = pose or random_pose(rng, portrait=h > w, doc_size=(w, h), frame=frame)
    bg, kind = background(rng, fw, fh, bg_kind)
    corners = project_corners(w, h, frame_w=fw, frame_h=fh, **pose)
    img = composite(bg, doc, corners)
    img = uneven_lighting(img, rng)
    if glare_at is None:  # one random glare blob somewhere on the document
        gx, gy = rng.uniform(0.1, 0.9) * w, rng.uniform(0.1, 0.9) * h
        glare_at = map_point(corners, w, h, (gx, gy))
    glare_peak = glare_peak if glare_peak is not None else float(rng.uniform(60, 110))
    glare_radius = glare_radius or (float(rng.uniform(50, 110)), float(rng.uniform(30, 70)))
    ang = glare_angle if glare_angle is not None else float(rng.uniform(0, math.pi))
    img = glare(img, glare_at, glare_radius, glare_peak, ang)
    blur = blur if blur is not None else float(rng.uniform(0.3, 0.8))
    noise = noise if noise is not None else float(rng.uniform(2.5, 6))
    out = finish(img, rng, blur, noise)
    if motion:
        out = motion_blur(out, *motion)
    meta = {
        "source": f"synth/{name}.json", "frame": [fw, fh], "background": kind, "pose_deg": pose,
        "corners_tl_tr_br_bl": corners.round(1).tolist(), "gaussian_blur_sigma": round(blur, 2),
        "noise_sigma": round(noise, 2), "glare": {"centre": [round(glare_at[0], 1), round(glare_at[1], 1)],
                                                    "radius": [round(r, 1) for r in glare_radius], "peak": round(glare_peak, 1)},
        "motion_blur": {"length": motion[0], "angle_deg": motion[1]} if motion else None,
    }
    return out, meta


def write(stem: str, img: np.ndarray, meta: dict, expect: str) -> None:
    CAMERA.mkdir(exist_ok=True)
    cv2.imwrite(str(CAMERA / f"{stem}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    meta = {"image": f"camera/{stem}.jpg", "expect": expect, **meta}
    (CAMERA / f"{stem}.json").write_text(json.dumps(meta, indent=2) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-doc", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    names = sorted(p.stem for p in SYNTH.glob("*.json"))
    for i, name in enumerate(names):
        rng = np.random.default_rng(args.seed * 1000 + i)
        doc, _ = load_doc(name)
        h, w = doc.shape[:2]
        for k in range(args.per_doc):
            img, meta = render(name, doc, rng, bg_kind="wood" if k % 2 == 0 else "desk")
            write(f"{name}_good_{k}", img, meta, "good")
        # BAD 1: heavy motion blur
        img, meta = render(name, doc, rng, motion=(int(rng.integers(35, 55)), float(rng.uniform(0, 180))))
        write(f"{name}_bad_motion", img, {**meta, "defect": "heavy motion blur"}, "bad")
        # BAD 2: about half the document out of frame
        pose = random_pose(rng, portrait=h > w)
        pose.update(cx=float(rng.choice([-0.02, 1.02])), cy=0.5)
        img, meta = render(name, doc, rng, pose=pose)
        write(f"{name}_bad_cropped", img, {**meta, "defect": "document about half out of frame"}, "bad")
        # BAD 3: strong glare over the MRZ / barcode / ID number
        fw, fh = frame_for(doc)
        pose = random_pose(rng, portrait=h > w, doc_size=(w, h), frame=(fw, fh))
        corners = project_corners(w, h, frame_w=fw, frame_h=fh, **pose)
        doc_w_px = float(np.linalg.norm(corners[1] - corners[0]))
        at = map_point(corners, w, h, region_of_interest(name, w, h))
        edge = corners[1] - corners[0]
        img, meta = render(name, doc, rng, pose=pose, glare_at=at, glare_peak=330.0,
                           glare_radius=(doc_w_px * 0.32, doc_w_px * 0.09),
                           glare_angle=math.atan2(float(edge[1]), float(edge[0])))
        what = "MRZ" if "passport" in name else ("identity number" if name.endswith("front") else "barcode")
        write(f"{name}_bad_glare", img, {**meta, "defect": f"strong glare over the {what}"}, "bad")
        print("camera:", name)


if __name__ == "__main__":
    main()
