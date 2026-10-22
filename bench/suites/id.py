"""Identity documents: accepted rate on good frames, false accepts on bad
frames, field-level exact match, MRZ check digits, native time per frame (fast
pass and OCR pass) and time-to-capture on the fake-camera clips.

Sets: `id_stills` (testdata/camera, DEV), `id_hard_dev` / `id_hard_test`
(bench/data/gen_id.py). Each frame is scanned by `examples/scan` (the same
`Scanner::analyse` the wasm runs, OCR on, no expected kind: eval/eval.py's
setting) on the browser guide's crop.

Scoring (eval/eval.py's fields and normalisation: upper case, letters and
digits only):
- accept_good: a good frame accepted *as the right kind*;
- false_accept_bad: a bad frame accepted at all (lower is better);
- accepted_wrong: a good frame accepted with the wrong kind or any field
  wrong: the costly error, so accepting more cannot hide behind accept_good;
- fields_exact: every scored field of every good frame, accepted or not;
- mrz_pass: passport good frames whose MRZ parsed with every check digit
  passing.

Time-to-capture (`clips`): each clip of `id_clips` is sampled at a fixed 4
frames per second of clip time and every sample scanned with the step's
expected kind, as the demo does; the capture is the second consecutive
accepted sample with the same reading (kind and ID number / MRZ) and the whole
outline in view. Fixed sampling makes this deterministic: it measures how soon
the frames become readable, not how fast the machine is (the speed metrics
do that). The 960x540 smart ID back clip must *not* capture (README: its bars
are about a pixel wide); every other clip must capture the right reading.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from lib.common import (CACHE, DATA, MANIFESTS, ROOT, Cache, binary, binary_key, env1, log, m_info, m_latency, m_rate, manifest_root,
                        manifest, run_jsonl_sharded, sha256_file, taskset, timed_runs, write_atomic)

MODELS = [ROOT / "models" / "text-detection.rten", ROOT / "models" / "text-recognition.rten"]
KIND = {"za_green_id_book": "za_green_book"}


def norm(s) -> str:
    return "".join(ch for ch in str(s or "").upper() if ch.isalnum())


def yymmdd(iso: str) -> str:
    return iso[2:4] + iso[5:7] + iso[8:10]


def fields_of(kind: str, truth: dict, r: dict) -> list[tuple[str, str, str]]:
    """(field, want, got) for the fields a kind should yield (eval/eval.py's score())."""
    f = truth["fields"]
    out = []
    if kind in ("za_passport", "gb_passport"):
        m = r.get("mrz") or {}
        out += [("surname", f["surname"], m.get("surname")), ("given_names", f["given_names"], m.get("given_names")),
                ("document_number", f["document_number"], m.get("document_number")),
                ("date_of_birth", yymmdd(f["date_of_birth"]), m.get("date_of_birth")),
                ("date_of_expiry", yymmdd(f["date_of_expiry"]), m.get("date_of_expiry"))]
    elif kind == "za_smart_id_back":
        b = r.get("smart_id_barcode") or {}
        out += [("id_number", f["identity_number"], (b.get("id_number") or {}).get("value"))]
    elif kind == "za_smart_id_front":
        p = r.get("printed") or {}
        for k in ("surname", "names", "sex", "nationality", "date_of_birth_printed", "country_of_birth", "status"):
            out.append((k, f[k], p.get(k.replace("_printed", ""))))
        out.append(("id_number", f["identity_number"], (p.get("id_number") or {}).get("value")))
    elif kind == "za_green_id_book":
        p = r.get("printed") or {}
        out += [("surname", f["surname"], p.get("surname")), ("names", f["forenames"], p.get("names")),
                ("id_number", f["identity_number"], (p.get("id_number") or {}).get("value"))]
    return out


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #


def guide_crop(src: Path, meta: dict, out: Path) -> Path:
    """eval/eval.py's crop of a camera still: the document's box plus 6%, at most 1280 wide."""
    if out.exists():
        return out
    from PIL import Image

    img = Image.open(src).convert("RGB")
    xs = [p[0] for p in meta["corners_tl_tr_br_bl"]]
    ys = [p[1] for p in meta["corners_tl_tr_br_bl"]]
    mx, my = (max(xs) - min(xs)) * 0.06, (max(ys) - min(ys)) * 0.06
    box = tuple(int(v) for v in (max(0, min(xs) - mx), max(0, min(ys) - my), min(img.width, max(xs) + mx), min(img.height, max(ys) + my)))
    c = img.crop(box)
    if c.width > 1280:
        c = c.resize((1280, round(c.height * 1280 / c.width)), Image.BILINEAR)
    import io

    buf = io.BytesIO()
    c.save(buf, format="PNG")
    write_atomic(out, buf.getvalue())
    return out


def items_of(set_name: str, quick: bool) -> list[dict]:
    root = manifest_root(manifest(set_name))
    out = []
    if set_name == "id_stills":
        for mp in sorted((root / "camera").glob("*.json")):
            meta = json.loads(mp.read_text())
            if json.loads((root / meta["source"]).read_text())["kind"] == "multi_barcode":
                continue
            img = guide_crop(root / meta["image"], meta, CACHE / "id_crops" / f"{mp.stem}.png")
            out.append({"id": mp.stem, "image": str(img), "truth": root / meta["source"], "expect": meta["expect"], "condition": mp.stem.split("_", 3)[-1]})
    else:
        for mp in sorted((root / "frames").glob("*.json")):
            meta = json.loads(mp.read_text())
            out.append({"id": meta["id"], "image": str(root / meta["image"]), "truth": root / meta["source"], "expect": meta["expect"],
                        "condition": meta["condition"], "holder": meta["holder"]})
    if quick:
        # A fixed subset: the stills' first good and bad frame per kind; one holder of the hard sets.
        if set_name == "id_stills":
            out = [x for x in out if x["id"].endswith(("_good_0", "_bad_motion", "_bad_cropped"))]
        else:
            out = [x for x in out if x["holder"] == 0]
    return out


def scan(items: list[dict], ctx, expect: str = "", sequence: bool = False) -> dict[str, dict]:
    """`examples/scan` on every image, cached by (binary, models, image bytes).

    Scanner::analyse remembers the orientation that last read (for a live
    feed), so a still's reading would depend on whichever still its process
    read before it, and so on --jobs: every still gets a process of its own.
    `sequence`: the items are one clip's frames, read in order by one process,
    as the live feed reads them."""
    key = binary_key("scan", models=MODELS) + (f"-{expect}" if expect else "")
    cache = Cache("id_scan_v2", key)  # v2: one process per still (v1 shared processes, so orientation memory leaked between stills)
    shas = {x["image"]: sha256_file(Path(x["image"])) for x in items}
    if sequence:  # a frame's reading depends on the frames before it: key it by the clip's prefix
        acc = hashlib.sha256()
        for x in items:
            acc.update(shas[x["image"]].encode())
            shas[x["image"]] = acc.hexdigest()
    todo = sorted({x["image"] for x in items if cache.get(shas[x["image"]]) is None})
    if todo:
        log(f"  id: scanning {len(todo)} frames ({len(items) - len(todo)} cached)")
        cmd = [str(binary("scan"))] + ([f"--expect={expect}"] if expect else [])
        if sequence:
            todo = [x["image"] for x in items]  # the whole clip, in order, every time
        runs = run_jsonl_sharded(cmd, todo, ctx.jobs, env1(SCAN_MAX_WIDTH="1280"), list_arg=None, per_item=not sequence,
                                 ordered=[todo] if sequence else None)
        for r in runs:
            r.pop("lines", None)
            if r.get("timeout") or r.get("crash"):  # a hang or a panic: nothing read, nothing accepted
                r.update(kind="timeout" if r.get("timeout") else "crash", accepted=False)
            cache.put(shas[r["path"]], r)
        cache.save()
    return {x["image"]: cache.get(shas[x["image"]]) for x in items}


# --------------------------------------------------------------------------- #


def score_set(tag: str, items: list[dict], res: dict[str, dict]) -> dict:
    good_ids, good_ok, wrong_ok = [], [], []
    bad_ids, bad_ok = [], []
    f_ids, f_ok = [], []
    mrz_ids, mrz_ok = [], []
    by_kind: dict = {}
    by_cond: dict = {}
    truths: dict = {}
    for x in items:
        r = res[x["image"]]
        t = truths.setdefault(x["truth"], json.loads(Path(x["truth"]).read_text()))
        kind = t["kind"]
        fields = fields_of(kind, t, r)
        right = [norm(w) == norm(g) for _, w, g in fields]
        kind_ok = r["kind"] == KIND.get(kind, kind)
        acc = bool(r["accepted"])
        bk = by_kind.setdefault(kind, {"good": 0, "accepted": 0, "fields": 0, "fields_right": 0, "bad": 0, "false_accepts": 0})
        bc = by_cond.setdefault(x["condition"], {"n": 0, "ok": 0})
        if x["expect"] == "good":
            good_ids.append(x["id"])
            good_ok.append(acc and kind_ok)
            wrong_ok.append(acc and not (kind_ok and all(right)))
            for (name, _, _), ok in zip(fields, right):
                f_ids.append(f"{x['id']}:{name}")
                f_ok.append(ok)
            if kind in ("za_passport", "gb_passport"):
                m = r.get("mrz") or {}
                mrz_ids.append(x["id"])
                mrz_ok.append(bool(m) and bool(m.get("checks")) and all(m["checks"].values()))
            bk["good"] += 1
            bk["accepted"] += acc and kind_ok
            bk["fields"] += len(right)
            bk["fields_right"] += sum(right)
            bc["n"] += 1
            bc["ok"] += acc and kind_ok and all(right)
        else:
            bad_ids.append(x["id"])
            bad_ok.append(acc)
            bk["bad"] += 1
            bk["false_accepts"] += acc
            bc["n"] += 1
            bc["ok"] += not acc
    p = f"id.{tag}"
    return {
        f"{p}.accept_good": m_rate(good_ids, good_ok, desc="good frames accepted as the right kind"),
        f"{p}.false_accept_bad": m_rate(bad_ids, bad_ok, desc="bad frames accepted (motion blur, half out of frame, glare over the read region, defocus)", better="lower"),
        f"{p}.accepted_wrong": m_rate(good_ids, wrong_ok, desc="good frames accepted with the wrong kind or a wrong field", better="lower"),
        f"{p}.fields_exact": m_rate(f_ids, f_ok, desc="fields of good frames exactly right (letters and digits, upper case)"),
        f"{p}.mrz_pass": m_rate(mrz_ids, mrz_ok, desc="passport good frames: MRZ read with every check digit passing"),
        f"{p}.by_kind": m_info(by_kind, desc="per document kind (good accepted, fields right, bad accepted)"),
        f"{p}.by_condition": m_info(by_cond, desc="per condition: good frames fully right / bad frames rejected"),
    }


# --------------------------------------------------------------------------- #
# Clips: time to capture
# --------------------------------------------------------------------------- #

CLIPS = [  # (file, expected step, capture expected)
    ("video/za_smart_id_front.y4m", "smart_id_front", True),
    ("video/za_smart_id_back.y4m", "smart_id_back", False),
    ("video/za_green_id_book.y4m", "green_book", True),
    ("video/za_passport.y4m", "passport", True),
    ("video/gb_passport.y4m", "passport", True),
    ("video/hd/za_smart_id_back.y4m", "smart_id_back", True),
]
SAMPLE_FPS = 4


def clip_frames(path: Path, step_s: float) -> list[tuple[float, Path]]:
    import cv2

    sha = sha256_file(path)[:16]
    d = CACHE / "id_clip_frames" / sha
    data = path.read_bytes()
    header, rest = data.split(b"\n", 1)
    toks = header.split()
    w = int([t for t in toks if t.startswith(b"W")][0][1:])
    h = int([t for t in toks if t.startswith(b"H")][0][1:])
    num, den = [t for t in toks if t.startswith(b"F")][0][1:].split(b":")
    fps = int(num) / int(den)
    size = w * h * 3 // 2
    frame_len = len(b"FRAME\n") + size
    n = len(rest) // frame_len
    out = []
    t = 0.0
    while round(t * fps) < n:
        k = int(round(t * fps))
        p = d / f"{k:04d}.png"
        if not p.exists():
            d.mkdir(parents=True, exist_ok=True)
            off = k * frame_len + len(b"FRAME\n")
            yuv = np.frombuffer(rest[off : off + size], np.uint8).reshape(h * 3 // 2, w)
            write_atomic(p, cv2.imencode(".png", cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420))[1].tobytes())
        out.append((round(t, 3), p))
        t += step_s
    return out


def reading(r: dict) -> str | None:
    if not r.get("accepted"):
        return None
    if r.get("mrz"):
        return r["kind"] + ":" + "".join(r["mrz"].get("lines") or [])
    b = (r.get("smart_id_barcode") or {}).get("id_number") or {}
    p = (r.get("printed") or {}).get("id_number") or {}
    return f"{r['kind']}:{b.get('value') or p.get('value')}"


def in_view(r: dict, w: int, h: int) -> bool:
    """The whole outline inside the frame (`analysed_size` is the flattened document's, not the frame's)."""
    d = r.get("document")
    if not d:
        return False
    return all(2 <= x <= w - 2 and 2 <= y <= h - 2 for x, y in d["corners"])


def clips(ctx) -> dict:
    root = manifest_root(manifest("id_clips"))
    stills = root / "synth"
    ids, ok, ttc_ids, ttc = [], [], [], []
    detail = {}
    todo = [(rel, expect, should) for rel, expect, should in CLIPS if not (ctx.quick and "hd" in rel)]
    frames_of = {rel: clip_frames(root / rel, 1 / SAMPLE_FPS) for rel, _, _ in todo}
    with ThreadPoolExecutor(max(1, min(ctx.jobs, len(todo)))) as ex:  # one process per clip, its frames in order
        results = dict(zip([t[0] for t in todo], ex.map(lambda t: scan([{"image": str(p)} for _, p in frames_of[t[0]]], ctx, t[1], sequence=True), todo)))
    for rel, expect, should in todo:
        clip = root / rel
        meta = json.loads(clip.with_suffix(".json").read_text())
        frames = frames_of[rel]
        res = results[rel]
        truth = json.loads((stills / Path(meta["source"]).name).read_text())
        prev, at, got = None, None, None
        for t, p in frames:
            r = res[str(p)]
            key = reading(r) if in_view(r, *meta["size"]) else None
            if key and key == prev:
                at, got = t, r
                break
            prev = key
        name = rel.replace("video/", "").replace(".y4m", "")
        if should:
            right = got is not None and all(norm(w) == norm(g) for _, w, g in fields_of(truth["kind"], truth, got))
            ids.append(name)
            ok.append(right)
            if right:
                ttc_ids.append(name)
                ttc.append(at)
        else:
            ids.append(name)
            ok.append(got is None)
        detail[name] = {"captured_at_s": at, "expected_capture": should, "samples": len(frames)}
    out = {"id.clips.outcome_right": m_rate(ids, ok, desc=f"clips sampled at {SAMPLE_FPS} fps: captured with the right reading (or, the 960x540 back, not captured)"),
           "id.clips.detail": m_info(detail, desc="per clip: capture time in clip seconds (null: none)")}
    if ttc:
        t = {"items": ttc_ids, "samples": ttc, "repeats": 1, "cpu": None, "load_start": None, "load_end": None}
        m = m_latency(t, desc=f"time to capture from the clip's start (clip seconds, {SAMPLE_FPS} fps sampling; deterministic)", unit="s")
        m["threads"] = None
        out["id.clips.time_to_capture_s"] = m
    return out


# --------------------------------------------------------------------------- #
# Speed: native, one pinned core, repeated
# --------------------------------------------------------------------------- #


def speed(ctx) -> dict:
    root = manifest_root(manifest("id_hard_dev"))
    holders = [0] if ctx.quick else [0, 1, 2]
    imgs = [str(root / "frames" / f"{k}_{h:02d}_base.png") for k in ("za_smart_id_front", "za_smart_id_back", "za_green_id_book", "za_passport", "gb_passport") for h in holders]
    def once(cpu):
        lines = []
        for img in imgs:  # a process per image: no orientation memory from the previous one
            r = subprocess.run(taskset(cpu) + [str(binary("scan")), img], capture_output=True, text=True, env=env1(SCAN_MAX_WIDTH="1280"), check=True)
            lines += r.stdout.splitlines()
        out_f, out_o = {}, {}
        for line in lines:
            d = json.loads(line)
            t = d["timings_ms"]
            name = Path(d["path"]).stem
            out_f[name] = t["quality"] + t["barcodes"]
            if t["ocr"] > 0:
                out_o[name] = t["ocr"]
        return {f"fast:{k}": v for k, v in out_f.items()} | {f"ocr:{k}": v for k, v in out_o.items()}

    t = timed_runs(once, min(ctx.repeats, 3))
    out = {}
    for pfx, name, desc in (("fast", "fast_ms", "fast pass per frame: outline, flatten, quality, barcodes"), ("ocr", "ocr_ms", "OCR pass per frame (orientation search included)")):
        sel = [i for i, k in enumerate(t["items"]) if k.startswith(pfx + ":")]
        if not sel:
            continue
        sub = {**t, "items": [t["items"][i].split(":", 1)[1] for i in sel], "samples": [t["samples"][i] for i in sel]}
        out[f"id.speed.{name}"] = m_latency(sub, desc=f"native, 1 thread, median over {t['repeats']} runs: {desc}")
    return out


def run(ctx) -> dict:
    if ctx.speed_only:
        return speed(ctx)
    out = {}
    sets = []
    if "dev" in ctx.splits:
        sets += [("stills", "id_stills"), ("hard_dev", "id_hard_dev")]
    if "test" in ctx.splits:
        sets += [("hard_test", "id_hard_test")]
    for tag, name in sets:
        items = items_of(name, ctx.quick)
        out.update(score_set(tag, items, scan(items, ctx)))
    if "dev" in ctx.splits and not ctx.skip_clips and (MANIFESTS / "id_clips.json").exists():
        out.update(clips(ctx))
    out.update(speed(ctx))
    return out
