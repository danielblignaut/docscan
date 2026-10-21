"""A procedural synthetic head, rendered in software: no real person anywhere.

The face is MediaPipe's canonical face mesh (468 vertices, 898 triangles, UV
coordinates; Apache-2.0, read from docscan/src/face/canonical.rs), its shape
perturbed per identity, painted with a texture drawn here from scratch (skin
tone, eyes, brows, lips, nostrils, shading) in the mesh's UV space. A skull
and hair (an ellipsoid), a neck and shoulders complete it. The renderer is a
z-buffered triangle rasteriser with perspective-correct texturing and Lambert
plus specular shading, so a turning head shows real parallax.

Nothing here is derived from a photograph or from a face dataset.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def load_canonical():
    src = (ROOT / "docscan/src/face/canonical.rs").read_text()

    def block(name):
        body = src.split(f"pub const {name}")[1].split("= [", 1)[1].split("];")[0]
        return [list(map(float, m.split(","))) for m in re.findall(r"\[([-0-9., ]+)\],", body)]

    v = np.array(block("VERTICES"), np.float64)
    uv = np.array(block("UV"), np.float64)
    f = np.array(block("TRIANGLES"), np.int64)
    return v, uv, f


VERTS, UVS, TRIS = load_canonical()

# Mesh index loops (MediaPipe's face mesh topology).
RIGHT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
LEFT_EYE = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
RIGHT_UPPER_LID = [246, 161, 160, 159, 158, 157, 173]
RIGHT_LOWER_LID = [7, 163, 144, 145, 153, 154, 155]
LEFT_UPPER_LID = [466, 388, 387, 386, 385, 384, 398]
LEFT_LOWER_LID = [249, 390, 373, 374, 380, 381, 382]
LIPS_OUTER = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
LIPS_INNER = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191]
RIGHT_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
LEFT_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
NOSE = [1, 2, 98, 327, 4, 5, 195, 197, 6, 168, 45, 275, 220, 440, 115, 344]

SKIN_TONES = [  # RGB, from very dark to light
    (74, 47, 34), (96, 62, 44), (120, 80, 56), (141, 98, 70), (168, 122, 90),
    (189, 145, 112), (205, 166, 134), (224, 188, 160), (236, 204, 180),
]
HAIR = [(20, 16, 14), (40, 28, 20), (70, 48, 30), (110, 80, 50), (150, 120, 80), (60, 60, 62)]
IRIS = [(60, 40, 25), (90, 60, 35), (50, 80, 110), (70, 100, 60), (35, 28, 22)]
CLOTH = [(40, 60, 110), (120, 30, 40), (30, 90, 70), (200, 200, 205), (50, 50, 55), (180, 130, 40)]


@dataclass
class Identity:
    seed: int
    skin: tuple
    hair: tuple
    iris: tuple
    cloth: tuple
    shape: np.ndarray = field(repr=False)  # per-vertex offsets, canonical cm
    bald: bool = False
    beard: float = 0.0

    @staticmethod
    def random(seed: int) -> "Identity":
        rng = np.random.default_rng(seed)
        v = VERTS
        # Smooth shape changes: face width, height, nose length and depth,
        # jaw width, eye spacing, chin, cheek fullness.
        off = np.zeros_like(v)
        w = rng.uniform(-0.08, 0.08)
        h = rng.uniform(-0.06, 0.06)
        off[:, 0] += v[:, 0] * w
        off[:, 1] += v[:, 1] * h
        nose = np.exp(-((v[:, 0] / 1.6) ** 2 + ((v[:, 1] + 1.5) / 3.0) ** 2))
        off[:, 2] += nose * rng.uniform(-0.5, 0.6)
        off[:, 0] += nose * v[:, 0] * rng.uniform(-0.15, 0.25)
        jaw = np.clip(-(v[:, 1] + 3) / 6, 0, 1)
        off[:, 0] += jaw * v[:, 0] * rng.uniform(-0.1, 0.12)
        eyes = np.exp(-(((np.abs(v[:, 0]) - 3.3) / 1.8) ** 2 + ((v[:, 1] - 2.5) / 1.4) ** 2))
        off[:, 0] += eyes * np.sign(v[:, 0]) * rng.uniform(-0.3, 0.3)
        chin = np.exp(-((v[:, 0] / 2.5) ** 2 + ((v[:, 1] + 8.5) / 1.5) ** 2))
        off[:, 1] += chin * rng.uniform(-0.6, 0.4)
        cheek = np.exp(-(((np.abs(v[:, 0]) - 4.5) / 2.0) ** 2 + ((v[:, 1] + 1.0) / 2.5) ** 2))
        off[:, 2] += cheek * rng.uniform(-0.3, 0.5)
        return Identity(
            seed=seed,
            skin=SKIN_TONES[rng.integers(len(SKIN_TONES))],
            hair=HAIR[rng.integers(len(HAIR))],
            iris=IRIS[rng.integers(len(IRIS))],
            cloth=CLOTH[rng.integers(len(CLOTH))],
            shape=off,
            bald=bool(rng.random() < 0.15),
            beard=float(rng.random() * 0.6 if rng.random() < 0.3 else 0.0),
        )


TEX = 1024


def uv_px(ids):
    uv = UVS[ids]
    return np.stack([uv[:, 0] * TEX, (1 - uv[:, 1]) * TEX], 1).astype(np.float32)


def make_texture(ident: Identity) -> np.ndarray:
    rng = np.random.default_rng(ident.seed + 1)
    skin = np.array(ident.skin, np.float32)
    tex = np.ones((TEX, TEX, 3), np.float32) * skin
    # Low-frequency skin variation and fine pores.
    for scale, amp in [(128, 6), (32, 3), (4, 2)]:
        n = rng.normal(0, 1, (TEX // scale + 2, TEX // scale + 2)).astype(np.float32)
        n = cv2.resize(n, (TEX, TEX), interpolation=cv2.INTER_CUBIC)
        tex += n[..., None] * amp
    # Warmer cheeks and nose, darker around the eyes.
    def blob(ids, colour, sigma, strength):
        m = np.zeros((TEX, TEX), np.float32)
        cv2.fillPoly(m, [uv_px(ids).astype(np.int32)], 1.0)
        m = cv2.GaussianBlur(m, (0, 0), sigma)
        return m[..., None] * (np.array(colour, np.float32) - tex) * strength

    tex += blob([116, 117, 118, 101, 205, 187, 123], (200, 90, 80), 30, 0.12)
    tex += blob([345, 346, 347, 330, 425, 411, 352], (200, 90, 80), 30, 0.12)
    tex += blob(RIGHT_EYE, skin * 0.6, 18, 0.5)
    tex += blob(LEFT_EYE, skin * 0.6, 18, 0.5)
    # Beard shadow.
    if ident.beard > 0:
        tex += blob([172, 136, 150, 149, 176, 148, 152, 377, 400, 378, 379, 365, 397, 288, 410, 287, 57, 186], (40, 32, 28), 25, ident.beard)
    # Eyes: sclera, iris, pupil, highlight, lid line.
    for loop in (RIGHT_EYE, LEFT_EYE):
        pts = uv_px(loop)
        m = np.zeros((TEX, TEX), np.float32)
        cv2.fillPoly(m, [pts.astype(np.int32)], 1.0)
        m = cv2.GaussianBlur(m, (0, 0), 1.5)[..., None]
        eye = np.ones((TEX, TEX, 3), np.float32) * np.array([228, 222, 215], np.float32)
        c = pts.mean(0)
        wdt = np.linalg.norm(pts[0] - pts[8])
        r = wdt * 0.24
        yy, xx = np.mgrid[0:TEX, 0:TEX]
        d = np.sqrt((xx - c[0]) ** 2 + (yy - c[1]) ** 2)
        iris = np.array(ident.iris, np.float32)
        ring = np.clip((r - d) / 2, 0, 1)[..., None]
        eye = eye * (1 - ring) + ring * (iris * (0.7 + 0.3 * np.clip(d / r, 0, 1)[..., None]))
        pupil = np.clip((r * 0.42 - d) / 1.5, 0, 1)[..., None]
        eye = eye * (1 - pupil) + pupil * 12
        hl = np.clip((r * 0.15 - np.sqrt((xx - c[0] - r * 0.3) ** 2 + (yy - c[1] + r * 0.3) ** 2)) / 1.5, 0, 1)[..., None]
        eye = eye * (1 - hl) + hl * 250
        tex = tex * (1 - m) + eye * m
        cv2.polylines(tex, [pts.astype(np.int32)], True, (skin * 0.35).tolist(), 3, cv2.LINE_AA)
    # Brows: dark strokes along the brow loop.
    brow = np.array(ident.hair, np.float32) * 0.9 + skin * 0.1
    for loop in (RIGHT_BROW, LEFT_BROW):
        pts = uv_px(loop)
        m = np.zeros((TEX, TEX), np.float32)
        cv2.fillPoly(m, [pts.astype(np.int32)], 1.0)
        hairs = (rng.random((TEX, TEX)) > 0.4).astype(np.float32)
        hairs = cv2.GaussianBlur(hairs, (0, 0), 1.2)
        m = cv2.GaussianBlur(m, (0, 0), 3)[..., None] * (0.6 + 0.4 * hairs[..., None])
        tex = tex * (1 - m * 0.9) + brow * m * 0.9
    # Lips.
    lip = np.array(ident.skin, np.float32) * np.array([1.0, 0.62, 0.62]) + np.array([30, 0, 5], np.float32)
    m = np.zeros((TEX, TEX), np.float32)
    cv2.fillPoly(m, [uv_px(LIPS_OUTER).astype(np.int32)], 1.0)
    m = cv2.GaussianBlur(m, (0, 0), 2.5)[..., None]
    tex = tex * (1 - m) + lip * m
    cv2.polylines(tex, [uv_px(LIPS_INNER).astype(np.int32)], True, (lip * 0.45).tolist(), 3, cv2.LINE_AA)
    # Nostrils.
    for i in (98, 327):
        c = uv_px([i])[0]
        cv2.ellipse(tex, (int(c[0]), int(c[1])), (9, 5), 0, 0, 360, (skin * 0.35).tolist(), -1, cv2.LINE_AA)
    tex = cv2.GaussianBlur(tex, (0, 0), 0.8)
    return np.clip(tex, 0, 255)


def ellipsoid(centre, radii, n_lat=24, n_lon=36):
    lat = np.linspace(-math.pi / 2, math.pi / 2, n_lat + 1)
    lon = np.linspace(0, 2 * math.pi, n_lon + 1)
    v, uv = [], []
    for a in lat:
        for b in lon:
            v.append([centre[0] + radii[0] * math.cos(a) * math.sin(b), centre[1] + radii[1] * math.sin(a), centre[2] + radii[2] * math.cos(a) * math.cos(b)])
            uv.append([b / (2 * math.pi), (a + math.pi / 2) / math.pi])
    f = []
    w = n_lon + 1
    for i in range(n_lat):
        for j in range(n_lon):
            p = i * w + j
            f.append([p, p + 1, p + w])
            f.append([p + 1, p + w + 1, p + w])
    return np.array(v), np.array(uv), np.array(f)


def cylinder(centre, radius, y0, y1, n=36):
    v, uv, f = [], [], []
    for k, y in enumerate([y0, y1]):
        for j in range(n + 1):
            b = 2 * math.pi * j / n
            v.append([centre[0] + radius * math.sin(b), y, centre[2] + radius * math.cos(b)])
            uv.append([j / n, k])
    for j in range(n):
        f.append([j, j + 1, n + 1 + j])
        f.append([j + 1, n + 2 + j, n + 1 + j])
    return np.array(v), np.array(uv), np.array(f)


@dataclass
class Part:
    verts: np.ndarray  # canonical cm (x right, y up, z towards camera)
    uv: np.ndarray
    tris: np.ndarray
    tex: np.ndarray  # H x W x 3 float
    moves_with_head: bool = True
    shininess: float = 0.25


class Head:
    def __init__(self, ident: Identity):
        self.ident = ident
        face_v = VERTS + ident.shape
        self.face = Part(face_v, UVS, TRIS, make_texture(ident))
        hair = np.array(ident.hair if not ident.bald else ident.skin, np.float32)
        rng = np.random.default_rng(ident.seed + 2)
        skin = np.array(ident.skin, np.float32)
        # The skull's texture by where each texel lands on the ellipsoid: hair
        # above the brow line and over the back, skin at the temples and ears.
        th, tw = 256, 512
        yy, xx = np.mgrid[0:th, 0:tw]
        lat = (1 - yy / (th - 1)) * math.pi - math.pi / 2  # texture row 0 = top (v = 1)
        lon = xx / (tw - 1) * 2 * math.pi
        py = 1.6 + 11.0 * np.sin(lat)
        pz = -4.6 + 8.3 * np.cos(lat) * np.cos(lon)
        hairline = 4.8 + 1.2 * np.cos(lon * 3)
        is_hair = (py > hairline) | (pz < -6.5) | ((py > 1.0) & (pz < -3.0))
        if ident.bald:
            is_hair = (pz < -9.0) & (py < 3.0) & (py > -2.0)
        noise = cv2.resize(rng.normal(0, 1, (64, 128)).astype(np.float32), (tw, th))[..., None]
        htex = np.where(is_hair[..., None], hair + noise * 10, skin * 0.92 + noise * 3)
        self.skull = Part(*ellipsoid((0, 1.6, -4.6), (8.1, 11.0, 8.3), 18, 28), htex.astype(np.float32), shininess=0.1)
        ntex = np.ones((8, 64, 3), np.float32) * skin * 0.85
        self.neck = Part(*cylinder((0, 0, -4.0), 5.3, -19, -6), ntex, moves_with_head=False, shininess=0.1)
        ctex = np.ones((32, 64, 3), np.float32) * np.array(ident.cloth, np.float32)
        self.torso = Part(*ellipsoid((0, -25, -4), (19, 9, 9), 10, 20), ctex, moves_with_head=False, shininess=0.05)
        self.lids = {"right": (RIGHT_UPPER_LID, RIGHT_LOWER_LID), "left": (LEFT_UPPER_LID, LEFT_LOWER_LID)}

    def face_vertices(self, blink: float = 0.0, smile: float = 0.0) -> np.ndarray:
        v = self.face.verts.copy()
        if blink > 0:
            for up, low in self.lids.values():
                for a, b in zip(up, low[::-1] if False else low):
                    pass
                lowc = v[low].mean(0)
                for i in up:
                    v[i, 1] += (lowc[1] - v[i, 1]) * blink * 0.9
        if smile:
            for i, s in [(61, -1), (291, 1)]:
                v[i, 0] += s * 0.3 * smile
                v[i, 1] += 0.35 * smile
        return v


@dataclass
class Camera:
    width: int = 480
    height: int = 640
    fov_deg: float = 62.0  # vertical

    @property
    def f(self):
        return self.height / 2 / math.tan(math.radians(self.fov_deg) / 2)


def rot(yaw, pitch, roll):
    """Canonical-frame rotation: yaw turns the face towards image right,
    pitch tilts it up, roll anticlockwise in the image (degrees)."""
    y, p, r = map(math.radians, (yaw, pitch, roll))
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rx = np.array([[1, 0, 0], [0, math.cos(p), math.sin(p)], [0, -math.sin(p), math.cos(p)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return rz @ rx @ ry


PIVOT = np.array([0.0, -7.0, -6.0])  # the top of the neck, canonical cm


def to_camera(v, R, t):
    """Canonical (y up, z towards camera) to camera (x right, y down, z
    forward), rotating about the neck pivot and translating by t (cm, camera
    frame)."""
    w = (v - PIVOT) @ R.T + PIVOT
    return np.stack([w[:, 0] + t[0], -w[:, 1] + t[1], -w[:, 2] + t[2]], 1)


class Raster:
    def __init__(self, cam: Camera, ss: int = 2):
        self.cam = cam
        self.ss = ss
        self.W, self.H = cam.width * ss, cam.height * ss
        self.f = cam.f * ss

    def begin(self, background: np.ndarray):
        self.img = cv2.resize(background, (self.W, self.H)).astype(np.float32)
        self.z = np.full((self.H, self.W), np.inf, np.float32)

    def draw(self, verts_cam: np.ndarray, normals_cam: np.ndarray, uv: np.ndarray, tris: np.ndarray, tex: np.ndarray, light, shininess):
        z = verts_cam[:, 2]
        x = self.f * verts_cam[:, 0] / z + self.W / 2
        y = self.f * verts_cam[:, 1] / z + self.H / 2
        th, tw = tex.shape[:2]
        L = np.array(light["dir"], np.float64)
        L /= np.linalg.norm(L)
        # Back-face culling: skip triangles whose mean normal points away
        # from the camera (at the origin, looking along +z).
        tn = normals_cam[tris].mean(1)
        tc = verts_cam[tris].mean(1)
        front = (tn * tc).sum(1) < 0.05 * np.linalg.norm(tc, axis=1)
        # Skip triangles entirely off screen or behind the camera.
        tx, ty_ = x[tris], y[tris]
        on = (tx.max(1) >= 0) & (tx.min(1) < self.W) & (ty_.max(1) >= 0) & (ty_.min(1) < self.H) & (z[tris].min(1) > 1)
        for t in tris[front & on]:
            a, b, c = t
            xs = np.array([x[a], x[b], x[c]])
            ys = np.array([y[a], y[b], y[c]])
            # Back-face cull (screen-space winding; the mesh winds anticlockwise seen from outside).
            area = (xs[1] - xs[0]) * (ys[2] - ys[0]) - (xs[2] - xs[0]) * (ys[1] - ys[0])
            if abs(area) < 1e-9:
                continue
            x0, x1 = int(max(0, math.floor(xs.min()))), int(min(self.W - 1, math.ceil(xs.max())))
            y0, y1 = int(max(0, math.floor(ys.min()))), int(min(self.H - 1, math.ceil(ys.max())))
            if x0 > x1 or y0 > y1:
                continue
            gy, gx = np.mgrid[y0 : y1 + 1, x0 : x1 + 1]
            px = gx + 0.5
            py = gy + 0.5
            w0 = ((xs[1] - px) * (ys[2] - py) - (xs[2] - px) * (ys[1] - py)) / area
            w1 = ((xs[2] - px) * (ys[0] - py) - (xs[0] - px) * (ys[2] - py)) / area
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            iz = np.array([1 / z[a], 1 / z[b], 1 / z[c]])
            zinv = w0 * iz[0] + w1 * iz[1] + w2 * iz[2]
            depth = 1 / zinv
            zb = self.z[y0 : y1 + 1, x0 : x1 + 1]
            vis = inside & (depth < zb)
            if not vis.any():
                continue
            # Perspective-correct attributes.
            k0, k1, k2 = w0 * iz[0] / zinv, w1 * iz[1] / zinv, w2 * iz[2] / zinv
            u = k0 * uv[a, 0] + k1 * uv[b, 0] + k2 * uv[c, 0]
            v = k0 * uv[a, 1] + k1 * uv[b, 1] + k2 * uv[c, 1]
            tx = np.clip(u * (tw - 1), 0, tw - 1)
            ty = np.clip((1 - v) * (th - 1), 0, th - 1)
            col = tex[ty.astype(np.int32)[vis], tx.astype(np.int32)[vis]]
            n = k0[vis, None] * normals_cam[a] + k1[vis, None] * normals_cam[b] + k2[vis, None] * normals_cam[c]
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
            # Lights in camera frame; the viewer looks along +z.
            diff = np.clip(-(n @ L), 0, 1)
            view = np.array([0, 0, -1.0])
            h = -L + view
            h /= np.linalg.norm(h)
            spec = np.clip(n @ h, 0, 1) ** 24 * shininess
            shade = light["ambient"] + light["diffuse"] * diff
            col = col * shade[:, None] + spec[:, None] * 255 * light["diffuse"]
            sub = self.img[y0 : y1 + 1, x0 : x1 + 1]
            sub[vis] = col
            zb[vis] = depth[vis]

    def end(self) -> np.ndarray:
        img = cv2.resize(self.img, (self.cam.width, self.cam.height), interpolation=cv2.INTER_AREA)
        return np.clip(img, 0, 255)


def vertex_normals(v, f):
    n = np.zeros_like(v)
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)


def render_head(head: Head, cam: Camera, background: np.ndarray, yaw, pitch, roll, t, light, blink=0.0, ss=1) -> np.ndarray:
    """One frame: the head at (yaw, pitch, roll) about the neck, its pivot
    translated to t = (x, y, z) cm in the camera frame."""
    R = rot(yaw, pitch, roll)
    I = np.eye(3)
    parts = [
        (head.torso, head.torso.verts, I),
        (head.neck, head.neck.verts, I),
        (head.skull, head.skull.verts, R),
        (head.face, head.face_vertices(blink), R),
    ]
    scene = []
    for part, v, rr in parts:
        vc = to_camera(v, rr, t)
        nrm = vertex_normals(v, part.tris)
        if part is head.face and nrm[:, 2].mean() < 0:
            nrm = -nrm
        nc = nrm @ rr.T
        nc = np.stack([nc[:, 0], -nc[:, 1], -nc[:, 2]], 1)
        scene.append((vc, nc, part))
    return rasterise(scene, cam, background, light, ss)


def rasterise(scene, cam: Camera, background: np.ndarray, light, ss=1) -> np.ndarray:
    """Painter's-order triangle IDs drawn by OpenCV (back faces culled), then
    every pixel shaded at once: perspective-correct UVs and normals from its
    triangle's barycentric coordinates, Lambert plus a specular highlight.

    `scene`: (camera-frame vertices, camera-frame normals, Part) per part."""
    W, H = cam.width * ss, cam.height * ss
    f = cam.f * ss
    tri_xy, tri_z, tri_ref = [], [], []
    for pi, (vc, nc, part) in enumerate(scene):
        z = vc[:, 2]
        xy = np.stack([f * vc[:, 0] / z + W / 2, f * vc[:, 1] / z + H / 2], 1)
        tris = part.tris
        tn = nc[tris].mean(1)
        tc = vc[tris].mean(1)
        front = (tn * tc).sum(1) < 0.05 * np.linalg.norm(tc, axis=1)
        txy = xy[tris]
        on = front & (txy[..., 0].max(1) >= 0) & (txy[..., 0].min(1) < W) & (txy[..., 1].max(1) >= 0) & (txy[..., 1].min(1) < H) & (z[tris].min(1) > 1)
        idx = np.nonzero(on)[0]
        tri_xy.append(txy[idx])
        tri_z.append(tc[idx, 2])
        tri_ref.append(np.stack([np.full(len(idx), pi), idx], 1))
    tri_xy = np.concatenate(tri_xy)
    tri_z = np.concatenate(tri_z)
    tri_ref = np.concatenate(tri_ref)
    order = np.argsort(-tri_z)  # far first
    ids = np.full((H, W), -1, np.int32)
    pts = np.round(tri_xy * 16).astype(np.int32)
    for k in order:
        cv2.fillConvexPoly(ids, pts[k], int(k), lineType=cv2.LINE_8, shift=4)
    img = cv2.resize(background, (W, H)).astype(np.float32)
    mask = ids >= 0
    ys, xs = np.nonzero(mask)
    k = ids[ys, xs]
    px, py = xs + 0.5, ys + 0.5
    L = np.array(light["dir"], np.float64)
    L /= np.linalg.norm(L)
    view = np.array([0, 0, -1.0])
    hv = -L + view
    hv /= np.linalg.norm(hv)
    for pi, (vc, nc, part) in enumerate(scene):
        sel = tri_ref[k, 0] == pi
        if not sel.any():
            continue
        kk = k[sel]
        ti = part.tris[tri_ref[kk, 1]]
        a, b, c = ti[:, 0], ti[:, 1], ti[:, 2]
        xy = tri_xy[kk]
        x0, y0 = xy[:, 0, 0], xy[:, 0, 1]
        x1, y1 = xy[:, 1, 0], xy[:, 1, 1]
        x2, y2 = xy[:, 2, 0], xy[:, 2, 1]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        area = np.where(np.abs(area) < 1e-9, 1e-9, area)
        qx, qy = px[sel], py[sel]
        w0 = ((x1 - qx) * (y2 - qy) - (x2 - qx) * (y1 - qy)) / area
        w1 = ((x2 - qx) * (y0 - qy) - (x0 - qx) * (y2 - qy)) / area
        w0 = np.clip(w0, 0, 1)
        w1 = np.clip(w1, 0, 1 - w0)
        w2 = 1 - w0 - w1
        iz0, iz1, iz2 = 1 / vc[a, 2], 1 / vc[b, 2], 1 / vc[c, 2]
        zinv = w0 * iz0 + w1 * iz1 + w2 * iz2
        k0, k1, k2 = w0 * iz0 / zinv, w1 * iz1 / zinv, w2 * iz2 / zinv
        uv = part.uv
        u = k0 * uv[a, 0] + k1 * uv[b, 0] + k2 * uv[c, 0]
        v = k0 * uv[a, 1] + k1 * uv[b, 1] + k2 * uv[c, 1]
        th, tw = part.tex.shape[:2]
        tx = np.clip(u * (tw - 1), 0, tw - 1).astype(np.int32)
        ty = np.clip((1 - v) * (th - 1), 0, th - 1).astype(np.int32)
        col = part.tex[ty, tx]
        n = k0[:, None] * nc[a] + k1[:, None] * nc[b] + k2[:, None] * nc[c]
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        diff = np.clip(-(n @ L), 0, 1)
        spec = np.clip(n @ hv, 0, 1) ** 24 * part.shininess
        shade = light["ambient"] + light["diffuse"] * diff
        img[ys[sel], xs[sel]] = col * shade[:, None] + spec[:, None] * 255 * light["diffuse"]
    if ss > 1:
        img = cv2.resize(img, (cam.width, cam.height), interpolation=cv2.INTER_AREA)
    return np.clip(img, 0, 255)


def room_background(cam: Camera, seed: int) -> np.ndarray:
    """A plain synthetic room: a wall gradient, a door or shelf, a lamp glow."""
    rng = np.random.default_rng(seed)
    h, w = cam.height, cam.width
    top = rng.uniform(140, 220, 3)
    bottom = top * rng.uniform(0.55, 0.85)
    t = np.linspace(0, 1, h)[:, None, None]
    img = (top * (1 - t) + bottom * t) * np.ones((h, w, 3))
    for _ in range(rng.integers(2, 5)):
        x0, y0 = rng.integers(0, w), rng.integers(0, h)
        x1, y1 = x0 + rng.integers(40, 200), y0 + rng.integers(40, 300)
        col = rng.uniform(40, 230, 3)
        cv2.rectangle(img, (int(x0), int(y0)), (int(x1), int(y1)), col.tolist(), -1)
    glow = np.zeros((h, w), np.float32)
    cv2.circle(glow, (int(rng.integers(0, w)), int(rng.integers(0, h // 2))), 60, 1.0, -1)
    glow = cv2.GaussianBlur(glow, (0, 0), 60)
    img += glow[..., None] * 80
    img = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 2.0)
    return np.clip(img, 0, 255).astype(np.float32)


def random_light(seed: int):
    rng = np.random.default_rng(seed)
    return {"dir": [rng.uniform(-0.5, 0.5), rng.uniform(0.1, 0.6), 1.0], "ambient": rng.uniform(0.45, 0.65), "diffuse": rng.uniform(0.45, 0.7)}


if __name__ == "__main__":
    import sys

    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    ident = Identity.random(seed)
    head = Head(ident)
    cam = Camera()
    bg = room_background(cam, seed)
    light = random_light(seed)
    tiles = []
    for yaw, pitch in [(0, 0), (25, 0), (-25, 0), (0, 20), (0, -20), (18, 18)]:
        tiles.append(render_head(head, cam, bg, yaw, pitch, 0, (0, 6.0, 38), light))
    out = np.concatenate([np.concatenate(tiles[:3], 1), np.concatenate(tiles[3:], 1)], 0)
    cv2.imwrite(sys.argv[2] if len(sys.argv) > 2 else "/tmp/head.png", out[..., ::-1].astype(np.uint8))
