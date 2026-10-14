"""Fake-webcam clips for headless Chrome's --use-file-for-fake-video-capture.

For each synth/<kind>.png writes video/<kind>.y4m (yuv420p, 30 fps): the
document starts out of frame and out of focus, slides and rotates into a
roughly centred pose, then holds still (sub-pixel hand tremor, sensor noise
only) for the rest of the clip. A video/<kind>.json beside it records the
timeline and the per-frame document corners.

Portrait documents (the green ID book) are held sideways, i.e. rotated 90 deg,
so the page's long edge runs along the frame's width, as staff do to fill a
landscape webcam frame.

Run: .venv/bin/python make_videos.py [--size 960x540] [--seconds 6] [--hold 2.5] [--only KIND ...] [--outdir video]
     HD variant of the dense ones (kept under 200 MB by shortening to 4.8 s):
     .venv/bin/python make_videos.py --size 1280x720 --seconds 4.8 --hold 2.2 --only za_smart_id_back multi_barcode --outdir video/hd
Then: chrome --use-fake-device-for-media-stream --use-file-for-fake-video-capture=video/<kind>.y4m
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

from augment import background, composite, glare, project_corners, smooth_noise

ROOT = Path(__file__).resolve().parent
SYNTH = ROOT / "synth"
VIDEO = ROOT / "video"  # replaced by --outdir


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def motion_kernel_blur(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    length = int(round(math.hypot(dx, dy)))
    if length < 2:
        return img
    k = np.zeros((length * 2 + 1, length * 2 + 1), np.float32)
    c = length
    cv2.line(k, (int(c - dx / 2), int(c - dy / 2)), (int(c + dx / 2), int(c + dy / 2)), 1.0, 1, cv2.LINE_AA)
    k /= k.sum()
    return cv2.filter2D(img, -1, k)


def video_name(kind: str) -> str:
    return "multi-barcode" if kind == "multi_barcode" else kind


def make(kind: str, size: tuple[int, int], seconds: float, hold: float, fps: int, seed: int) -> dict:
    W, H = size
    rng = np.random.default_rng(seed)
    doc = cv2.imread(str(SYNTH / f"{kind}.png"), cv2.IMREAD_COLOR)
    if doc.shape[0] > doc.shape[1]:
        doc = cv2.rotate(doc, cv2.ROTATE_90_COUNTERCLOCKWISE)
        rotated = True
    else:
        rotated = False
    dh, dw = doc.shape[:2]
    bg, bg_kind = background(rng, W, H, "wood" if seed % 2 else "desk")
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    ang = rng.uniform(0, 2 * math.pi)
    gain = (1 + 0.3 * ((xx / W - 0.5) * math.cos(ang) + (yy / H - 0.5) * math.sin(ang)))
    gain *= 1 - 0.3 * ((xx / W - 0.5) ** 2 + (yy / H - 0.5) ** 2) * 2
    gain *= 0.92 + 0.16 * smooth_noise(rng, H, W, 200)
    glare_c = (rng.uniform(0.3, 0.7) * W, rng.uniform(0.3, 0.7) * H)
    glare_r = (rng.uniform(0.05, 0.09) * W, rng.uniform(0.03, 0.06) * W)

    n = int(round(seconds * fps))
    t_arrive = seconds - hold  # pose is final from here on
    t_start = 0.35 * t_arrive  # out of frame until here
    final = {"rx": float(rng.uniform(-6, 6)), "ry": float(rng.uniform(-6, 6)), "rz": float(rng.uniform(-5, 5)),
             "width_frac": 0.86, "cx": 0.5 + float(rng.uniform(-0.02, 0.02)), "cy": 0.5 + float(rng.uniform(-0.02, 0.02))}
    # Fill the frame as far as possible while keeping the whole document (2% margin) in view.
    while True:
        c = project_corners(dw, dh, frame_w=W, frame_h=H, **final)
        if c[:, 0].min() >= 0.02 * W and c[:, 0].max() <= 0.98 * W and c[:, 1].min() >= 0.02 * H and c[:, 1].max() <= 0.98 * H:
            break
        final["width_frac"] -= 0.01
    side = float(rng.choice([-1, 1]))
    start = {"rx": float(rng.uniform(-25, 25)), "ry": float(rng.uniform(-30, 30)), "rz": 35.0 * side,
             "width_frac": 0.55, "cx": 0.5 + 1.0 * side, "cy": 0.5 + float(rng.uniform(-0.25, 0.25))}

    # Write YUV4MPEG2 directly (the Playwright ffmpeg build has no rawvideo demuxer):
    # header, then "FRAME\n" + I420 planes (Y, U, V) per frame. Same layout ffmpeg emits for yuv420p.
    out = (VIDEO / f"{video_name(kind)}.y4m").open("wb")
    out.write(f"YUV4MPEG2 W{W} H{H} F{fps}:1 Ip A1:1 C420jpeg XYSCSS=420JPEG\n".encode())
    frames = []
    prev = None
    for i in range(n):
        t = i / fps
        a = ease((t - t_start) / (t_arrive - t_start))
        pose = {k: lerp(start[k], final[k], a) for k in final}
        if t >= t_arrive:  # hold: tiny hand tremor only
            pose["cx"] += 0.0006 * math.sin(2 * math.pi * 1.3 * t)
            pose["cy"] += 0.0006 * math.cos(2 * math.pi * 0.9 * t)
        corners = project_corners(dw, dh, frame_w=W, frame_h=H, **pose)
        img = composite(bg, doc, corners)
        img = img * gain[..., None]
        img = glare(img, glare_c, glare_r, 70.0)
        # focus: blurry while arriving, sharp on hold
        focus = lerp(4.0, 0.45, ease((t - t_start * 0.5) / (t_arrive - t_start * 0.5)))
        img = cv2.GaussianBlur(img, (0, 0), focus)
        centre = corners.mean(axis=0)
        if prev is not None and t < t_arrive:
            d = (centre - prev) * 0.8
            img = motion_kernel_blur(img, float(d[0]), float(d[1]))
        prev = centre
        img = img + rng.normal(0, 3.0, img.shape).astype(np.float32)
        out.write(b"FRAME\n")
        out.write(cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2YUV_I420).tobytes())
        frames.append({"t": round(t, 3), "corners_tl_tr_br_bl": corners.round(1).tolist(), "focus_sigma": round(focus, 2)})
    out.close()
    meta = {
        "kind": kind, "source": f"synth/{kind}.json", "video": str((VIDEO / f"{video_name(kind)}.y4m").relative_to(ROOT)), "size": [W, H], "fps": fps,
        "frames": n, "background": bg_kind, "document_rotated_90": rotated,
        "timeline_s": {"out_of_frame_until": round(t_start, 2), "arrives": round(t_arrive, 2), "holds_until": seconds},
        "final_pose_deg": final, "per_frame": frames,
    }
    (VIDEO / f"{video_name(kind)}.json").write_text(json.dumps(meta) + "\n")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="960x540")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--hold", type=float, default=2.5)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--outdir", default="video")
    args = ap.parse_args()
    global VIDEO
    VIDEO = ROOT / args.outdir
    W, H = map(int, args.size.split("x"))
    VIDEO.mkdir(exist_ok=True)
    kinds = args.only or sorted(p.stem for p in SYNTH.glob("*.png"))
    for i, kind in enumerate(kinds):
        make(kind, (W, H), args.seconds, args.hold, args.fps, seed=100 + i)
        size_mb = (VIDEO / f"{video_name(kind)}.y4m").stat().st_size / 1e6
        print(f"video: {video_name(kind)}.y4m {W}x{H} {size_mb:.0f} MB")


if __name__ == "__main__":
    main()
