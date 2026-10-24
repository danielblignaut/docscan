"""Bounded, content-preserving optics hypotheses; no learned restoration.

Inputs are RGB uint8 display images. Inverse sRGB is an explicit approximation
to scene-linear light, NOT recovery of sensor RAW or an unknown camera response.
All constants are frozen by hashing this file before inference.
"""
import cv2
import numpy as np

cv2.setNumThreads(1)
ARMS = ("baseline", "global_exposure", "local_illumination")
CONDITIONS = ("clean", "dark", "shadow", "glare", "motion_blur")


def linear(rgb):
    x = rgb.astype(np.float32) / 255
    return np.where(x <= .04045, x / 12.92, ((x + .055) / 1.055) ** 2.4)


def encode(x):
    x = np.clip(x, 0, 1)
    return np.rint(255 * np.where(x <= .0031308, 12.92 * x,
                                1.055 * x ** (1 / 2.4) - .055)).astype(np.uint8)


def luminance(x):
    return x @ np.array([.2126, .7152, .0722], np.float32)


def thumb(rgb, cap=512):
    h, w = rgb.shape[:2]
    scale = min(1, cap / max(h, w))
    return cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))),
                      interpolation=cv2.INTER_AREA) if scale < 1 else rgb


def background(rgb):
    y = luminance(linear(thumb(rgb)))
    # A fixed coarse radius suppresses glyphs, then a smooth field avoids edges.
    b = cv2.dilate(y, np.ones((25, 25), np.uint8))
    return cv2.GaussianBlur(b, (0, 0), 9)


def preprocess(rgb, arm):
    if arm == "baseline":
        return rgb, {"changed": False}
    bg = background(rgb)
    lo, hi = np.percentile(bg, [10, 90])
    meta = {"background_p10": float(lo), "background_p90": float(hi)}
    active = hi < .55 or (arm == "local_illumination" and lo / max(hi, .01) < .65)
    if not active:
        return rgb, {**meta, "changed": False}
    if arm == "global_exposure":
        gain = min(4., .85 / max(float(hi), .01))
    elif arm == "local_illumination":
        gain = cv2.resize(np.clip(.85 / np.maximum(bg, .01), 1, 4),
                          (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)[..., None]
    else:
        raise ValueError("unknown arm")
    out = encode(linear(rgb) * gain)
    return out, {**meta, "changed": not np.array_equal(out, rgb)}


def diagnostic(rgb):
    """Conservative bright-island suspicion, not a calibrated glare detector.

    White paper alone is not glare. A clipped flat island needs a darker ring.
    This mask never edits pixels or changes acceptance; it only ranks frames.
    """
    y = luminance(linear(thumb(rgb)))
    clipped = (y >= .98).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(clipped)
    suspect = np.zeros(y.shape, np.uint8)
    for label in range(1, n):
        area = stats[label, cv2.CC_STAT_AREA] / y.size
        if not .001 <= area <= .25:
            continue
        part = (labels == label).astype(np.uint8)
        ring = (cv2.dilate(part, np.ones((11, 11), np.uint8)) > 0) & (part == 0)
        if np.any(ring) and np.median(y[ring]) < .88:
            suspect[part > 0] = 1
    # Gradient energy is normalized for exposure, but can still reward noise.
    dx = cv2.Sobel(y, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(y, cv2.CV_32F, 0, 1, ksize=3)
    focus = float(np.mean(dx * dx + dy * dy) / max(float(np.mean(y * y)), .01))
    glare = float(suspect.mean())
    exposure = min(1., float(np.percentile(y, 90)) / .35)
    return {"focus_proxy": focus, "glare_suspect_fraction": glare,
            "selection_score": focus * exposure * (1 - min(.8, glare * 8))}


def degrade(rgb, condition, seed):
    if condition == "clean":
        return rgb
    x = linear(rgb)
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[:h, :w].astype(np.float32)
    xx /= max(1, w - 1)
    yy /= max(1, h - 1)
    if condition == "dark":
        # -2.47 EV; shot/read noise in linear light, fixed per specimen seed.
        rng = np.random.default_rng(seed)
        x = rng.poisson(x * .18 * 3000).astype(np.float32) / 3000
        x += rng.normal(0, .001, x.shape).astype(np.float32)
    elif condition == "shadow":
        illumination = .18 + .70 / (1 + np.exp(-(xx - .48) / .05))
        x *= illumination[..., None]
    elif condition == "glare":
        # Additive veiling/specular light clips evidence; it is never restored.
        specular = 1.4 * np.exp(-(((xx - .56) / .20) ** 2 + ((yy - .48) / .15) ** 2) / 2)
        x += specular[..., None]
    elif condition == "motion_blur":
        kernel = np.zeros((7, 7), np.float32)
        kernel[3, :] = 1 / 7
        x = cv2.filter2D(x, -1, kernel, borderType=cv2.BORDER_REFLECT_101)
    else:
        raise ValueError("unknown condition")
    return encode(x)
