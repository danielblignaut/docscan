"""Synthetic liveness clips: bona fide head sweeps and presentation attacks,
as .y4m files for Chrome's fake camera and for the native eval.

Every face is a procedural synthetic head (head.py); no real person.

Kinds:
- bona_fide: centre, then turn the head round a full circle (start angle,
  direction, radius, speed, distance, light, background all random), then
  face the camera again;
- photo: a printed photo of a synthetic head, held up and tilted round the
  same circle (the attack the ring invites: tilting a flat photo makes the
  face *look* turned);
- curved_photo: the same print bent round a cylinder (a harder flat attack);
- screen: a bona fide sweep video replayed on a phone screen held in front of
  the camera (bezel, pixel grid moiré, colour cast, reflections);
- video_2d: a 2-D face video injected full frame: the frontal photo squeezed
  and shifted as if turning, with no parallax;
- partial: a real head that turns only half way round, then stops.

Usage:
  python clips.py --kind bona_fide --seed 1000 --out /tmp/face-data/clips/dev
  python clips.py --set dev|test --jobs 10          # the DEV and TEST sets (face/eval/liveness.py)
  python clips.py --e2e                              # testdata/video/face/*.y4m for demo/e2e
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from head import Camera, Head, Identity, Part, random_light, rasterise, render_head, room_background, rot  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FPS = 30
KINDS = ["bona_fide", "photo", "curved_photo", "screen", "video_2d", "partial"]


class Y4M:
    def __init__(self, path: Path, w: int, h: int, fps: int = FPS):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = path.open("wb")
        self.f.write(f"YUV4MPEG2 W{w} H{h} F{fps}:1 Ip A1:1 C420jpeg XYSCSS=420JPEG\n".encode())
        self.n = 0

    def write(self, rgb: np.ndarray):
        self.f.write(b"FRAME\n")
        self.f.write(cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2YUV_I420).tobytes())
        self.n += 1

    def close(self):
        self.f.close()


def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def camera_noise(img, rng, sigma=2.5):
    """Sensor noise, a touch of blur, and auto-exposure flicker."""
    img = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 0.6)
    img = img * rng.uniform(0.985, 1.015) + rng.normal(0, sigma, img.shape)
    return np.clip(img, 0, 255)


def sweep_path(rng, n_frames_hold=None, partial=False, slow=False):
    """Screen directions (degrees right, up) per frame: hold, ramp out,
    round the circle, ramp in, hold. Returns a list of (right, up).
    `slow`: a 6 s sweep after a 2 s hold (the e2e clips, analysed by the
    single-threaded wasm at a few frames a second)."""
    hold0 = int((rng.uniform(1.9, 2.1) if slow else rng.uniform(0.9, 1.4)) * FPS)
    ramp = int(rng.uniform(0.35, 0.6) * FPS)
    sweep = int((rng.uniform(6.0, 6.5) if slow else rng.uniform(3.6, 5.2)) * FPS)
    hold1 = int(rng.uniform(1.0, 1.4) * FPS)
    radius = rng.uniform(21, 28)
    start = rng.uniform(0, 360)
    sign = 1 if rng.random() < 0.5 else -1
    total = 400 if not partial else rng.uniform(150, 200)
    wobble_f = rng.uniform(0.5, 1.2)
    path = []
    for _ in range(hold0):
        path.append((0.0, 0.0))
    for i in range(ramp):
        a = math.radians(start)
        r = radius * smoothstep(i / ramp)
        path.append((r * math.sin(a), r * math.cos(a)))
    for i in range(sweep):
        t = i / sweep
        # Uneven speed: slower round the bottom, as people do.
        a = math.radians(start + sign * total * (t + 0.04 * math.sin(2 * math.pi * t)))
        r = radius * (1 + 0.12 * math.sin(2 * math.pi * wobble_f * t + start))
        path.append((r * math.sin(a), r * math.cos(a)))
    end = math.radians(start + sign * total)
    for i in range(ramp):
        r = radius * (1 - smoothstep(i / ramp))
        path.append((r * math.sin(end), r * math.cos(end)))
    for _ in range(hold1 if not partial else int(4 * FPS)):
        path.append((0.0, 0.0))
    return path


def bona_fide(seed: int, out: Path, partial=False, size=(480, 640), slow=False):
    rng = np.random.default_rng(seed)
    ident = Identity.random(seed)
    head = Head(ident)
    cam = Camera(*size, fov_deg=rng.uniform(58, 68))
    bg = room_background(cam, seed + 7)
    light = random_light(seed + 3)
    dist = rng.uniform(34, 44)
    neutral_pitch = rng.uniform(-6, 4)  # people look slightly down at a screen
    ty = rng.uniform(-1.0, 1.5)  # the face centred in the frame, as the guide asks
    path = sweep_path(rng, partial=partial, slow=slow)
    y4m = Y4M(out, *size)
    truth = []
    blink_at = set(int(x) for x in rng.choice(len(path), size=2, replace=False)) if rng.random() < 0.6 else set()
    blink = 0
    for i, (right, up) in enumerate(path):
        yaw = -right  # the preview is mirrored: screen right is the camera's left
        pitch = up + neutral_pitch
        roll = 2.5 * math.sin(i / 23.0 + seed) + 0.15 * right
        # The head moves a little as it turns.
        t = (0.25 * right * 0.1 + rng.normal(0, 0.05), ty - 0.1 * up * 0.2 + rng.normal(0, 0.05), dist + rng.normal(0, 0.1))
        if i in blink_at:
            blink = 4
        b = [0, 0.6, 1.0, 1.0, 0.5][blink] if blink else 0.0
        blink = max(0, blink - 1)
        img = render_head(head, cam, bg, yaw, pitch, roll, t, light, blink=b, ss=1)
        y4m.write(camera_noise(img, rng))
        truth.append({"right": round(right, 2), "up": round(up, 2)})
    y4m.close()
    return {"kind": "partial" if partial else "bona_fide", "seed": seed, "frames": len(path), "truth": truth}


def frontal_photo(seed: int, w=600, h=800):
    """A head-and-shoulders portrait of a synthetic head, as printed or shown."""
    rng = np.random.default_rng(seed + 11)
    head = Head(Identity.random(seed))
    cam = Camera(w, h, fov_deg=40)
    bg = room_background(cam, seed + 13)
    img = render_head(head, cam, bg, rng.uniform(-4, 4), rng.uniform(-3, 3), 0, (0, rng.uniform(-1.0, 1.5), 46), random_light(seed + 5), ss=1)
    return img


def plane_corners(cam: Camera, w_cm, h_cm, yaw, pitch, roll, t):
    """The four corners of a w x h cm plane at pose (camera frame), projected."""
    R = rot(yaw, pitch, roll)
    pts = np.array([[-w_cm / 2, h_cm / 2, 0], [w_cm / 2, h_cm / 2, 0], [w_cm / 2, -h_cm / 2, 0], [-w_cm / 2, -h_cm / 2, 0]])
    p = pts @ R.T
    cam_pts = np.stack([p[:, 0] + t[0], -p[:, 1] + t[1], -p[:, 2] + t[2]], 1)
    f = cam.f
    return np.stack([f * cam_pts[:, 0] / cam_pts[:, 2] + cam.width / 2, f * cam_pts[:, 1] / cam_pts[:, 2] + cam.height / 2], 1).astype(np.float32), R


def composite_plane(frame, content, corners, alpha_edge=1.0):
    h, w = content.shape[:2]
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32)
    H = cv2.getPerspectiveTransform(src, corners)
    W, Hh = frame.shape[1], frame.shape[0]
    warped = cv2.warpPerspective(content, H, (W, Hh), flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.ones((h, w), np.float32), H, (W, Hh), flags=cv2.INTER_LINEAR)[..., None]
    return frame * (1 - mask) + warped * mask


def print_effects(img, rng):
    """A print: lower contrast and saturation, warm paper, halftone-ish grain, a white border."""
    g = img.mean(2, keepdims=True)
    img = g + (img - g) * rng.uniform(0.75, 0.9)
    img = img * rng.uniform(0.8, 0.92) + np.array([18, 14, 8]) * rng.uniform(0.5, 1.5)
    grain = rng.normal(0, 4, img.shape[:2])[..., None]
    img = img + grain
    border = int(img.shape[1] * 0.05)
    img = cv2.copyMakeBorder(img.astype(np.float32), border, border, border, border, cv2.BORDER_CONSTANT, value=(238, 236, 228))
    return np.clip(img, 0, 255)


def photo_attack(seed: int, out: Path, size=(480, 640), slow=False):
    rng = np.random.default_rng(seed)
    cam = Camera(*size, fov_deg=rng.uniform(58, 68))
    bg = room_background(cam, seed + 7)
    photo = print_effects(frontal_photo(seed), rng)
    ph, pw = photo.shape[:2]
    w_cm = rng.uniform(14, 18)
    h_cm = w_cm * ph / pw
    dist = rng.uniform(20, 27)  # held so the face fills the oval
    path = sweep_path(rng, slow=slow)
    # An attacker watching the ring tilts as far as it takes: a tilted print
    # reads as only a slightly turned face, so far further than a head turns.
    gain = rng.uniform(2.0, 2.8)
    y4m = Y4M(out, *size)
    for i, (right, up) in enumerate(path):
        yaw, pitch = -right * gain, up * gain
        jitter = rng.normal(0, 0.15, 3)
        t = (jitter[0], jitter[1], dist + jitter[2])
        corners, R = plane_corners(cam, w_cm, h_cm, yaw, pitch, rng.normal(0, 1.0), t)
        # Light falls off as the print turns away; a glossy sheen at some angles.
        n = R @ np.array([0, 0, 1.0])
        shade = 0.75 + 0.25 * max(0.0, n[2]) + rng.normal(0, 0.005)
        content = photo * shade
        sheen = max(0.0, 1 - abs(yaw - 15) / 12) * rng.uniform(0, 60)
        content = content + sheen
        frame = composite_plane(bg.copy(), content, corners)
        y4m.write(camera_noise(frame, rng))
    y4m.close()
    return {"kind": "photo", "seed": seed, "frames": len(path)}


def curved_photo(seed: int, out: Path, size=(480, 640)):
    """The print bent round a vertical cylinder, rendered as a mesh."""
    rng = np.random.default_rng(seed)
    cam = Camera(*size, fov_deg=rng.uniform(58, 68))
    bg = room_background(cam, seed + 7)
    photo = print_effects(frontal_photo(seed), rng).astype(np.float32)
    ph, pw = photo.shape[:2]
    w_cm = rng.uniform(13, 17)
    h_cm = w_cm * ph / pw
    radius = rng.uniform(9, 14)
    dist = rng.uniform(16, 22)
    # A grid mesh on the cylinder (axis vertical, bulging towards the camera).
    nx, ny = 32, 16
    verts, uv, tris = [], [], []
    half_angle = (w_cm / 2) / radius
    for j in range(ny + 1):
        for i in range(nx + 1):
            a = -half_angle + 2 * half_angle * i / nx
            verts.append([radius * math.sin(a), h_cm / 2 - h_cm * j / ny, radius * math.cos(a) - radius])
            uv.append([i / nx, 1 - j / ny])
    for j in range(ny):
        for i in range(nx):
            p = j * (nx + 1) + i
            tris.append([p, p + nx + 1, p + 1])
            tris.append([p + 1, p + nx + 1, p + nx + 2])
    verts, uv, tris = np.array(verts), np.array(uv), np.array(tris)
    sheet = Part(verts, uv, tris, photo, shininess=0.2)
    path = sweep_path(rng)
    gain = rng.uniform(2.0, 2.8)
    y4m = Y4M(out, *size)
    light = {"dir": [0.2, 0.3, 1.0], "ambient": 0.6, "diffuse": 0.45}
    for i, (right, up) in enumerate(path):
        R = rot(-right * gain, up * gain, rng.normal(0, 1.0))
        jitter = rng.normal(0, 0.15, 3)
        w = verts @ R.T
        vc = np.stack([w[:, 0] + jitter[0], -w[:, 1] + jitter[1], -w[:, 2] + dist + jitter[2]], 1)
        nrm = np.stack([np.sin(np.arctan2(verts[:, 0], verts[:, 2] + radius)), np.zeros(len(verts)), np.cos(np.arctan2(verts[:, 0], verts[:, 2] + radius))], 1) @ R.T
        nc = np.stack([nrm[:, 0], -nrm[:, 1], -nrm[:, 2]], 1)
        y4m.write(camera_noise(rasterise([(vc, nc, sheet)], cam, bg, light), rng))
    y4m.close()
    return {"kind": "curved_photo", "seed": seed, "frames": len(path)}


def screen_attack(seed: int, out: Path, size=(480, 640)):
    """A bona fide sweep (another render of a synthetic head) replayed on a phone held up to the camera."""
    rng = np.random.default_rng(seed)
    cam = Camera(*size, fov_deg=rng.uniform(58, 68))
    bg = room_background(cam, seed + 7)
    # The replayed video: a bona fide sweep at the screen's resolution.
    src_seed = seed + 50000
    tmp = out.with_suffix(".src.y4m")
    meta = bona_fide(src_seed, tmp, size=(360, 480))
    frames = read_y4m(tmp)
    tmp.unlink()
    w_cm = rng.uniform(6.5, 7.5)
    h_cm = w_cm * 16 / 9
    dist = rng.uniform(9, 11.5)  # close enough that the replayed face fills the oval
    cast = np.array([rng.uniform(0.9, 1.0), rng.uniform(0.95, 1.02), rng.uniform(1.02, 1.12)])
    gamma = rng.uniform(0.85, 1.15)
    y4m = Y4M(out, *size)
    yaw0, pitch0 = rng.normal(0, 4), rng.normal(0, 4)
    for i, src in enumerate(frames):
        # Fit the 3:4 video into the 9:16 screen, black bars, a bezel.
        sh, sw = 1280, 720
        screen = np.zeros((sh, sw, 3), np.float32)
        # The attacker zooms the replay onto the face (the central half of the frame).
        h0, w0 = src.shape[:2]
        cw, ch = int(w0 * 0.5), int(h0 * 0.5)
        y0c = (h0 - ch) // 2 + int(0.05 * h0)  # the face sits a little below the frame centre
        crop = src[y0c : y0c + ch, (w0 - cw) // 2 : (w0 + cw) // 2]
        fh = min(sh, int(sw * crop.shape[0] / crop.shape[1]))
        y0 = (sh - fh) // 2
        screen[y0 : y0 + fh] = cv2.resize(crop.astype(np.float32), (sw, fh))
        screen = 255 * (np.clip(screen, 0, 255) / 255) ** gamma * cast
        # RGB sub-pixel stripes; downsampling them aliases into moiré.
        stripes = np.ones((sh, sw, 3), np.float32) * 0.9
        for k in range(3):
            stripes[:, k::3, k] = 1.1
        screen = screen * stripes
        bezel = cv2.copyMakeBorder(screen, 40, 40, 20, 20, cv2.BORDER_CONSTANT, value=(12, 12, 14))
        jitter = rng.normal(0, 0.12, 3)
        t = (jitter[0], 1.0 + jitter[1], dist + jitter[2])
        corners, _ = plane_corners(cam, w_cm + 0.6, h_cm + 1.2, yaw0 + rng.normal(0, 0.3), pitch0 + rng.normal(0, 0.3), rng.normal(0, 0.4), t)
        frame = composite_plane(bg.copy(), bezel, corners)
        # A reflection of the room on the glass.
        refl = cv2.GaussianBlur(bg, (0, 0), 25)
        quad = np.zeros(frame.shape[:2], np.float32)
        cv2.fillConvexPoly(quad, corners.astype(np.int32), 1.0)
        frame = frame + quad[..., None] * refl * rng.uniform(0.05, 0.15)
        y4m.write(camera_noise(frame, rng))
    y4m.close()
    return {"kind": "screen", "seed": seed, "frames": len(frames), "source_seed": src_seed}


def video_2d(seed: int, out: Path, size=(480, 640)):
    """A frontal photo animated in 2-D and injected as the whole camera
    frame: each frame the photo warped by the homography of a plane turned
    the way the head should turn (what a simple 2-D face animation does),
    with no parallax inside the face."""
    rng = np.random.default_rng(seed)
    cam_w, cam_h = size
    cam = Camera(cam_w, cam_h, fov_deg=62)
    photo = frontal_photo(seed, cam_w, cam_h)
    path = sweep_path(rng)
    gain = rng.uniform(2.0, 2.8)
    # The photo fills a plane that fills the frame at distance d.
    d = 40.0
    h_cm = 2 * d * math.tan(math.radians(62) / 2)
    w_cm = h_cm * cam_w / cam_h
    y4m = Y4M(out, *size)
    for right, up in path:
        corners, _ = plane_corners(cam, w_cm, h_cm, -right * gain, up * gain, 0.0, (0, 0, d))
        frame = composite_plane(np.zeros((cam_h, cam_w, 3), np.float32), photo.astype(np.float32), corners)
        # Fill what the warp uncovers with the photo's own edges, as a generator would.
        empty = (frame.sum(2) == 0)[..., None]
        frame = np.where(empty, cv2.GaussianBlur(photo.astype(np.float32), (0, 0), 15), frame)
        y4m.write(camera_noise(frame, rng, sigma=1.5))
    y4m.close()
    return {"kind": "video_2d", "seed": seed, "frames": len(path)}


def read_y4m(path: Path):
    data = path.read_bytes()
    header, rest = data.split(b"\n", 1)
    toks = header.split()
    w = int([t for t in toks if t.startswith(b"W")][0][1:])
    h = int([t for t in toks if t.startswith(b"H")][0][1:])
    size = w * h * 3 // 2
    frames = []
    off = 0
    while off < len(rest):
        off = rest.index(b"\n", off) + 1
        yuv = np.frombuffer(rest[off : off + size], np.uint8).reshape(h * 3 // 2, w)
        frames.append(cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420))
        off += size
    return frames


MAKERS = {
    "e2e_bona_fide": lambda s, o: bona_fide(s, o, slow=True),
    "e2e_photo": lambda s, o: photo_attack(s, o, slow=True),
    "bona_fide": lambda s, o: bona_fide(s, o),
    "partial": lambda s, o: bona_fide(s, o, partial=True),
    "photo": photo_attack,
    "curved_photo": curved_photo,
    "screen": screen_attack,
    "video_2d": video_2d,
}

# DEV and TEST: disjoint seeds (so disjoint synthetic identities, motions,
# lights and backgrounds). TEST is generated once and never used for tuning.
SETS = {
    "dev": {"bona_fide": range(1000, 1030), "photo": range(1100, 1115), "curved_photo": range(1200, 1210), "screen": range(1300, 1310), "video_2d": range(1400, 1410), "partial": range(1500, 1505)},
    "test": {"bona_fide": range(5000, 5040), "photo": range(5100, 5120), "curved_photo": range(5200, 5215), "screen": range(5300, 5315), "video_2d": range(5400, 5410), "partial": range(5500, 5510)},
}


def job(args):
    kind, seed, out = args
    if Path(out).exists() and Path(out).with_suffix(".json").exists():
        return json.loads(Path(out).with_suffix(".json").read_text())
    meta = MAKERS[kind](seed, Path(out))
    Path(out).with_suffix(".json").write_text(json.dumps(meta))
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=KINDS)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="/tmp/face-data/clips")
    ap.add_argument("--set", choices=list(SETS))
    ap.add_argument("--e2e", action="store_true")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    if a.e2e:
        d = ROOT / "testdata/video/face"
        jobs = [("e2e_bona_fide", 77, str(d / "bona-fide.y4m")), ("e2e_photo", 78, str(d / "photo-attack.y4m"))]
    elif a.set:
        d = Path(a.out) / a.set
        jobs = [(k, s, str(d / f"{k}_{s}.y4m")) for k, seeds in SETS[a.set].items() for s in seeds]
    else:
        jobs = [(a.kind, a.seed, str(Path(a.out) / f"{a.kind}_{a.seed}.y4m"))]
    with ProcessPoolExecutor(a.jobs) as ex:
        for meta in ex.map(job, jobs):
            print(meta["kind"], meta["seed"], meta["frames"])
