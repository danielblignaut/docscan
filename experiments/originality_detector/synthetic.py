"""Rights-free procedural optics stress fixtures, NOT a physical camera simulator.

All graphics are invented geometry: no people, identity fields, fonts, signatures,
third-party assets or author weights. A clean print duplicate is deliberately
indistinguishable from a first capture; absence of cues must not prove original.
"""
from __future__ import annotations
import cv2
import numpy as np


def render(seed, specimen, device, condition, size):
    w, h = size
    # Identical content/nuisance seed across a specimen's capture conditions.
    rng = np.random.default_rng(np.random.SeedSequence([seed, specimen]))
    drng = np.random.default_rng(np.random.SeedSequence([seed, device, 981]))
    y, x = np.mgrid[:h, :w].astype(np.float32)
    xn, yn = x/w, y/h
    box = (int(w*.17), int(h*.17), int(w*.83), int(h*.83))
    x0, y0, x1, y1 = box
    mask = np.zeros((h, w), np.float32); mask[y0:y1+1, x0:x1+1] = 1
    base = np.full((h, w, 3), rng.uniform(.30, .65), np.float32)
    base += rng.normal(0, .008, base.shape).astype(np.float32)
    base[y0:y1+1, x0:x1+1] = rng.uniform(.70, .92, 3)
    # Decorative lines and pseudo writing are used in EVERY class.
    for line in range(9):
        yy = y0+10+line*max(5, (y1-y0-20)//9)
        for start in range(x0+8, x1-20, 22):
            cv2.line(base, (start, yy), (min(start+int(rng.integers(8, 21)), x1-5), yy),
                     tuple(float(v) for v in rng.uniform(.10, .40, 3)), 1)
    for stroke in range(6):
        xx = np.linspace(x0+8, x1-8, 70)
        yy = y0+(y1-y0)*(.20+.11*stroke)+5*np.sin(xx*rng.uniform(.07, .18)+rng.uniform(0, 6))
        cv2.polylines(base, [np.c_[xx, yy].astype(np.int32)], False, (.35, .23, .31), 1)
    # Security linework is both a benign hard case and part of attack content.
    freq = rng.uniform(18, 32)
    wave = np.sin(2*np.pi*(freq*xn + 4*yn + .4*np.sin(yn*12)))
    security = wave[:, :, None]*np.array([.05, -.025, .035])*mask[:, :, None]
    base += security.astype(np.float32)
    if condition == 'security':
        base += security*2.5
    if condition in ('mono', 'print_gray'):
        base[:] = base.mean(axis=2, keepdims=True)
    if condition in ('halftone', 'print_color'):
        dot = np.sin(x*1.6)*np.sin(y*1.3)
        base -= (dot > .25)[:, :, None]*mask[:, :, None]*.10
    if condition == 'calligraphy':
        for stroke in range(20):
            t = np.linspace(0, 2*np.pi, 70)
            cx, cy = rng.uniform(x0+15, x1-15), rng.uniform(y0+15, y1-15)
            pts = np.c_[cx+12*np.cos(t), cy+8*np.sin(t)*np.cos(t)]
            cv2.polylines(base, [pts.astype(np.int32)], False, (.08, .11, .18), 1)
    if condition.startswith('screen'):
        # Screen artifacts may cross the apparent document boundary. Strong and
        # weak patterns share the same content; grayscale is a hard attack.
        angle = drng.uniform(.1, 2.9)
        frequency = drng.uniform(14, 35)
        pattern = np.sin(2*np.pi*frequency*(xn*np.cos(angle)+yn*np.sin(angle)) + rng.uniform(0, 6))
        amp = .06 if condition == 'screen_strong' else .015
        color = np.array([1., -.8, .5]) if condition != 'screen_achromatic' else np.ones(3)
        base += (amp*pattern[:, :, None]*color).astype(np.float32)
    if condition.startswith('print') and condition != 'print_clean':
        # A second imaging cycle; the negatives include grayscale/halftone too.
        base = cv2.GaussianBlur(base, (0, 0), .65)
    # Common photography nuisance independent of class.
    slope = rng.uniform(-.25, .25)
    base *= (.9+slope*(xn-.5))[:, :, None]
    base *= drng.uniform(.9, 1.1, 3).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), float(drng.uniform(.25, .65)))
    base += rng.normal(0, drng.uniform(.003, .008), base.shape).astype(np.float32)
    if condition == 'glare':
        glare = .5*np.exp(-((xn-.55)**2/.009+(yn-.35)**2/.02))
        base += glare[:, :, None]
    if condition == 'dim':
        base *= .35
    rgb = np.round(np.clip(base, 0, 1)*255).astype(np.uint8)
    quality = 35 if condition == 'jpeg' else int(drng.integers(75, 96))
    ok, encoded = cv2.imencode('.jpg', rgb[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError('JPEG encoding failed')
    rgb = cv2.imdecode(encoded, cv2.IMREAD_COLOR)[:, :, ::-1]
    quad = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return rgb, quad
