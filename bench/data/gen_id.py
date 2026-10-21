"""The harder identity-document set: many fictional holders per document kind,
photographed in many more conditions than testdata/camera.

testdata/camera (testdata/augment.py, seed 7) has one holder per kind and
gentle poses, and it was tuned on; this set exists so that improvements are
judged on documents and conditions nobody tuned for. It reuses the repo's own
generators: testdata/synth.py draws each document (its `passport()` and the
smart ID / green book functions, with the module's holder dicts replaced per
holder) and testdata/augment.py places it on a desk (`render`), so the
documents and scenes are the ones the scanner already knows, only harder.

Per split, `--holders` fictional holders for each of the five kinds (SA smart
ID front and back, SA green ID book, SA passport, UK passport); each holder is
photographed in every condition below. Good frames must be accepted with the
right fields; bad frames must not be accepted (the capture would not be a
usable record).

Good: `base` (augment.py's own range), `tilt` (25-35 deg about x and y),
`rot90` / `rot180` / `rot270` (sideways and upside down, +-8 deg), `small`
(the document a third of the frame wide), `lowres` (a 640-wide frame),
`blur` (gaussian 1.2-2.0 px), `dim` (a third to a half of the light, more
noise), `bright` (overexposed, clipped), `glare` (a strong glare blob away
from the machine-read region), `shadow` (a soft-edged shadow over half the
document), `jpeg` (quality 25-40), `combo` (moderate tilt, dim and blur).
Bad: `motion` (heavy motion blur), `cropped` (about half out of frame),
`glare_roi` (strong glare over the MRZ, barcode or ID number), `defocus`
(gaussian 5-7 px).

Each frame is stored as the browser's guide would crop it (the document's
bounding box plus 6%, at most 1280 px wide; eval/eval.py's crop), as PNG, with
a JSON beside it: the source truth, the condition, expect good/bad, the
document corners in the crop, and the pose.

Seeds: DEV 1000, TEST 2000 (the split picks it). Every frame has its own RNG
from (seed, kind, holder, condition), so the set does not depend on --jobs.

  python bench/data/gen_id.py --out /tmp/docscan-bench/id/hard_dev --split dev [--holders 6]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "testdata"))
import augment as A  # noqa: E402
import synth as S  # noqa: E402

SEEDS = {"dev": 1000, "test": 2000}
KINDS = ["za_smart_id_front", "za_smart_id_back", "za_green_id_book", "za_passport", "gb_passport"]
GOOD = ["base", "tilt", "rot90", "rot180", "rot270", "small", "lowres", "blur", "dim", "bright", "glare", "shadow", "jpeg", "combo"]
BAD = ["motion", "cropped", "glare_roi", "defocus"]

# Fictional names only. A generated value must also never contain a string the
# repository's privacy check looks for (some real values it guards are short
# digit runs a random number could hit). The strings themselves must not be
# written here, so they are held as hashes: every substring of a value of the
# right length is hashed and looked up.
PRIVATE_LENGTHS = (5, 6, 7, 8)
PRIVATE_HASHES = {
    "jwpxkvpwwzjfpqzzpvxzvyff", "kxkyqwkzzwxxzjxpjpfkqwfz", "pvpqfjyzxkxpfzfffppkpyqj", "pvyjzzjqzvwwvvkxkjkjxzzw",
    "qjqqykxqvxqjzfjqppjxqfvf", "qqyxxxxfqfkpxvwvpfqfwzqx", "vjpqvwxzxjwyjywzqpyqjzvk", "vjykpjwkzkqjwyywvfkvvxxq",
    "vkqypywpxjvjpqkxpwkqkqwv", "yffpwwxvpjpwzkqwwzzxfkpj", "yqfkykvfpjjyzjwkxzjkjfkk", "ywwfwqzqwpwyvyyjwqvpyypz",
    "zfzvyqvfwwqzzqvqqfzfvqpv",
}


def _digest(s: str) -> str:
    n = int(hashlib.sha256(s.encode()).hexdigest(), 16)
    out = []
    while n:
        n, r = divmod(n, 10)
        out.append("fjkpqvwxyz"[r])
    return "".join(reversed(out))[:24]


SURNAMES = ["MOKOENA", "DLAMINI", "VAN WYK", "PILLAY", "NAIDOO", "BOTHA", "KHUMALO", "NDLOVU", "SMIT", "JACOBS", "MAHLANGU",
            "PETERSEN", "LE ROUX", "MTHEMBU", "GOVENDER", "FOURIE", "SITHOLE", "NEL", "ZULU", "CLOETE", "HARTLEY", "OKAFOR",
            "MENSAH", "FORSYTH", "PRENTICE", "WHITCOMBE", "KOWALSKI", "MOKOENA-SMIT", "DU PREEZ", "RADEBE", "TSHABALALA"]
GIVEN = ["THANDIWE", "SIPHO", "LERATO", "JOHAN", "PRIYA", "AYANDA", "PIETER", "NOMVULA", "KAREN", "BONGANI", "FATIMA",
         "DAVID", "LINDIWE", "GRANT", "ZODWA", "MEERA", "HENDRIK", "PALESA", "OWEN", "AMAHLE", "RUTH", "TSHEPO", "ELSA", "KABELO"]
PLACES_ZA = ["JOHANNESBURG", "DURBAN", "CAPE TOWN", "PRETORIA", "POLOKWANE", "KIMBERLEY", "MTHATHA", "GEORGE"]
PLACES_UK = ["LEEDS", "BRISTOL", "CARDIFF", "NORWICH", "YORK", "EXETER"]


def safe(*values) -> bool:
    """No value contains a privacy-checked string (upper-cased, any position)."""
    for v in values:
        u = str(v).upper()
        for n in PRIVATE_LENGTHS:
            if any(_digest(u[i : i + n]) in PRIVATE_HASHES for i in range(len(u) - n + 1)):
                return False
    return True


def rdate(r: random.Random, a: dt.date, b: dt.date) -> dt.date:
    return a + dt.timedelta(days=r.randrange((b - a).days))


def holder(seed: int, kind: str, k: int) -> dict:
    """A fictional holder, re-drawn until no value trips the privacy check."""
    for attempt in range(100):
        r = random.Random(f"idhard:{seed}:{kind}:{k}:{attempt}")
        female = r.random() < 0.5
        dob = rdate(r, dt.date(1950, 1, 1), dt.date(2005, 12, 31))
        surname = r.choice(SURNAMES)
        names = " ".join(r.sample(GIVEN, r.choice([1, 2, 2, 3])))
        idn = S.make_sa_id(dob, female=female, seq=r.randrange(5000))
        issue = rdate(r, dt.date(2015, 1, 1), dt.date(2025, 6, 30))
        h = {"female": female, "dob": dob, "surname": surname, "names": names, "identity_number": idn, "issue": issue,
             "expiry": issue.replace(year=issue.year + 10) - dt.timedelta(days=1),
             "za_number": "A" + "".join(r.choice("0123456789") for _ in range(8)),
             "gb_number": "".join(r.choice("0123456789") for _ in range(9)),
             "security_number": "".join(r.choice("0123456789") for _ in range(5)),
             "card_number": "1" + "".join(r.choice("0123456789") for _ in range(8)),
             "pob_za": r.choice(PLACES_ZA), "pob_uk": r.choice(PLACES_UK)}
        if safe(*h.values()):
            return h
    raise RuntimeError("no privacy-safe holder")


def draw(kind: str, h: dict, out: Path, stem: str) -> None:
    """Renders one document with synth.py's own drawing code into out/<stem>.png|json."""
    S.OUT = out
    sex = "F" if h["female"] else "M"
    if kind in ("za_smart_id_front", "za_smart_id_back"):
        S.SMART.update(surname=h["surname"], names=h["names"], sex=sex, dob=h["dob"], date_of_issue=h["issue"],
                       security_number=h["security_number"], card_number=h["card_number"], identity_number=h["identity_number"])
        (S.sa_smart_front if kind.endswith("front") else S.sa_smart_back)()
        name = kind
    elif kind == "za_green_id_book":
        S.GREEN.update(surname=h["surname"], forenames=h["names"], dob=h["dob"], date_issued=h["issue"], identity_number=h["identity_number"])
        S.sa_green_book()
        name = kind
    elif kind == "za_passport":
        S.passport(stem, state="ZAF", header="REPUBLIC OF SOUTH AFRICA", nationality_text="SOUTH AFRICAN", surname=h["surname"],
                   given=h["names"], number=h["za_number"], dob=h["dob"], sex=sex, issue=h["issue"], expiry=h["expiry"],
                   pob=h["pob_za"], authority="DHA", optional=h["identity_number"], bg=(232, 236, 244), accent=(20, 70, 50), seed=10)
        name = stem
    else:
        S.passport(stem, state="GBR", header="UNITED KINGDOM OF GREAT BRITAIN AND NORTHERN IRELAND", nationality_text="BRITISH CITIZEN",
                   surname=h["surname"], given=h["names"], number=h["gb_number"], dob=h["dob"], sex=sex, issue=h["issue"],
                   expiry=h["expiry"], pob=h["pob_uk"], authority="HMPO", optional="", bg=(240, 236, 246), accent=(60, 30, 100),
                   seed=20, empty_optional_check="0")
        name = stem
    if name != stem:
        (out / f"{name}.png").replace(out / f"{stem}.png")
        (out / f"{name}.json").replace(out / f"{stem}.json")
    t = json.loads((out / f"{stem}.json").read_text())
    t.update(name=stem, image=f"docs/{stem}.png", kind=kind)
    if kind == "za_passport":
        t["fields"]["identity_number"] = h["identity_number"]
    (out / f"{stem}.json").write_text(json.dumps(t, indent=2, ensure_ascii=False) + "\n")


def _pose(rng, portrait: bool, cond: str) -> dict:
    p = A._pose(rng, portrait)
    if cond in ("tilt",):
        p["rx"] = float(rng.choice([-1, 1]) * rng.uniform(25, 35))
        p["ry"] = float(rng.choice([-1, 1]) * rng.uniform(25, 35))
        p["width_frac"] = float(rng.uniform(0.5, 0.65))
    elif cond in ("rot90", "rot180", "rot270"):
        p["rz"] = float({"rot90": 90, "rot180": 180, "rot270": 270}[cond] + rng.uniform(-8, 8))
        p["width_frac"] = float(rng.uniform(0.42, 0.55)) if cond != "rot180" else p["width_frac"]
    elif cond == "small":
        p["width_frac"] = float(rng.uniform(0.3, 0.42))
    elif cond == "combo":
        p["rx"], p["ry"] = float(rng.uniform(-22, 22)), float(rng.uniform(-22, 22))
    return p


def fit_pose(rng, doc: np.ndarray, frame: tuple[int, int], cond: str) -> dict:
    h, w = doc.shape[:2]
    for _ in range(400):
        p = _pose(rng, h > w, cond)
        c = A.project_corners(w, h, frame_w=frame[0], frame_h=frame[1], **p)
        mx, my = 0.03 * frame[0], 0.03 * frame[1]
        if c[:, 0].min() >= mx and c[:, 0].max() <= frame[0] - mx and c[:, 1].min() >= my and c[:, 1].max() <= frame[1] - my:
            return p
    raise RuntimeError(f"no in-frame pose for {cond}")


def guide_crop(img: np.ndarray, corners: np.ndarray) -> tuple[np.ndarray, np.ndarray, list]:
    """eval/eval.py's crop: the bounding box plus 6%, clamped, at most 1280 wide."""
    xs, ys = corners[:, 0], corners[:, 1]
    mx, my = (xs.max() - xs.min()) * 0.06, (ys.max() - ys.min()) * 0.06
    H, W = img.shape[:2]
    box = [int(max(0, xs.min() - mx)), int(max(0, ys.min() - my)), int(min(W, xs.max() + mx)), int(min(H, ys.max() + my))]
    c = img[box[1] : box[3], box[0] : box[2]]
    scale = 1.0
    if c.shape[1] > 1280:
        scale = 1280 / c.shape[1]
        c = cv2.resize(c, (1280, round(c.shape[0] * scale)), interpolation=cv2.INTER_LINEAR)
    return c, (corners - np.array([box[0], box[1]], np.float32)) * scale, box


def shadow(img: np.ndarray, rng) -> np.ndarray:
    h, w = img.shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = rng.uniform(0, 2 * math.pi)
    d = (x - w / 2) * math.cos(ang) + (y - h / 2) * math.sin(ang)
    soft = rng.uniform(10, 40)
    k = 1 - rng.uniform(0.45, 0.6) * (1 / (1 + np.exp(-d / soft)))
    return img * k[..., None]


def frame(job) -> dict:
    seed, kind, k, cond, out = job
    out = Path(out)
    stem = f"{kind}_{k:02d}"
    doc = cv2.imread(str(out / "docs" / f"{stem}.png"), cv2.IMREAD_COLOR)
    truth_rel = f"docs/{stem}.json"
    digest = int(hashlib.sha256(f"{kind}:{k}:{cond}".encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng([seed, digest])
    h, w = doc.shape[:2]
    fr = A.frame_for(doc)
    kw: dict = {}
    if cond == "cropped":
        p = A.random_pose(rng, portrait=h > w)
        p.update(cx=float(rng.choice([-0.02, 1.02])), cy=0.5)
        kw["pose"] = p
    elif cond == "glare_roi":
        p = fit_pose(rng, doc, fr, "base")
        corners = A.project_corners(w, h, frame_w=fr[0], frame_h=fr[1], **p)
        width_px = float(np.linalg.norm(corners[1] - corners[0]))
        edge = corners[1] - corners[0]
        kw.update(pose=p, glare_at=A.map_point(corners, w, h, A.region_of_interest(kind, w, h)), glare_peak=330.0,
                  glare_radius=(width_px * 0.32, width_px * 0.09), glare_angle=math.atan2(float(edge[1]), float(edge[0])))
    else:
        kw["pose"] = fit_pose(rng, doc, fr, cond)
    if cond == "glare":
        p = kw["pose"]
        corners = A.project_corners(w, h, frame_w=fr[0], frame_h=fr[1], **p)
        rx, ry = A.region_of_interest(kind, w, h)
        gx, gy = (w - rx) % w, (h - ry) % h  # the opposite side from the machine-read region
        kw.update(glare_at=A.map_point(corners, w, h, (gx, gy)), glare_peak=float(rng.uniform(170, 230)),
                  glare_radius=(float(rng.uniform(90, 140)), float(rng.uniform(60, 100))))
    if cond in ("blur", "combo"):
        kw["blur"] = float(rng.uniform(1.2, 2.0) if cond == "blur" else rng.uniform(0.9, 1.3))
    if cond == "defocus":
        kw["blur"] = float(rng.uniform(5, 7))
    if cond == "motion":
        kw["motion"] = (int(rng.integers(35, 55)), float(rng.uniform(0, 180)))
    if cond in ("dim", "combo"):
        kw["noise"] = float(rng.uniform(7, 10))
    img, meta = A.render(kind, doc, rng, frame=fr, **kw)
    x = img.astype(np.float32)
    if cond in ("dim", "combo"):
        x *= rng.uniform(0.33, 0.5) if cond == "dim" else rng.uniform(0.55, 0.7)
    if cond == "bright":
        x = x * rng.uniform(1.3, 1.5) + rng.uniform(10, 30)
    if cond == "shadow":
        x = shadow(x, rng)
    img = np.clip(x, 0, 255).astype(np.uint8)
    corners = np.array(meta["corners_tl_tr_br_bl"], np.float32)
    if cond == "lowres":
        s = 640 / img.shape[1] if img.shape[1] >= img.shape[0] else 360 / img.shape[1]
        img = cv2.resize(img, (round(img.shape[1] * s), round(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
        corners = corners * s
    q = int(rng.uniform(25, 40)) if cond == "jpeg" else int(rng.uniform(84, 92))
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    img = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    crop, cc, box = guide_crop(img, corners)
    name = f"{stem}_{cond}"
    (out / "frames").mkdir(exist_ok=True)
    cv2.imwrite(str(out / "frames" / f"{name}.png"), crop, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    rec = {"id": name, "image": f"frames/{name}.png", "source": truth_rel, "kind": kind, "holder": k, "condition": cond,
           "expect": "bad" if cond in BAD else "good", "jpeg_quality": q, "frame_size": [img.shape[1], img.shape[0]],
           "crop_box": box, "corners_tl_tr_br_bl": cc.round(1).tolist(),
           **{key: meta[key] for key in ("pose_deg", "gaussian_blur_sigma", "noise_sigma", "glare", "motion_blur", "background")}}
    (out / "frames" / f"{name}.json").write_text(json.dumps(rec, indent=1) + "\n")
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", choices=list(SEEDS), required=True)
    ap.add_argument("--holders", type=int, default=6)
    ap.add_argument("--seed", type=int, help="override the split's seed")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else SEEDS[a.split]
    out = Path(a.out)
    (out / "docs").mkdir(parents=True, exist_ok=True)
    for kind in KINDS:
        for k in range(a.holders):
            draw(kind, holder(seed, kind, k), out / "docs", f"{kind}_{k:02d}")
    jobs = [(seed, kind, k, c, str(out)) for kind in KINDS for k in range(a.holders) for c in GOOD + BAD]
    with ProcessPoolExecutor(a.jobs) as ex:
        n = sum(1 for _ in ex.map(frame, jobs, chunksize=4))
    print(f"{n} frames ({len(KINDS)} kinds x {a.holders} holders x {len(GOOD)} good + {len(BAD)} bad conditions) -> {out}")


if __name__ == "__main__":
    main()
