"""Barcode-photo latency experiment runner (DEV only). See README.md.

    run.py user       the user's photo: raw, full and ROI labelled readings,
                      cold (fresh process) and warm (in process), on one CPU
    run.py calibrate  DEV labelled frames, even index: every margin variant
                      (writes calibration.json; freeze with `run.py freeze`)
    run.py evaluate   DEV labelled frames, odd index (held out) and all: the
                      frozen candidate against the full reading and the truth
    run.py latency    DEV labelled frames: full vs frozen ROI ms on one CPU

The probe's stdout holds decoded and printed values. They are parsed here in
memory and never printed or written: outputs are counts, rates, timings and
opaque frame ids, written to the private experiment directory (and copied to
`evidence/` by hand only when they contain nothing else).
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EXP = Path(os.environ.get("BARCODE_LATENCY_DIR", "/tmp/docscan-barcode-latency-v1"))
PROBE = EXP / "bin" / "latency_probe"
REPO = Path(__file__).resolve().parents[2]
MODELS = REPO / "models"
DATA = Path(os.environ.get("BENCH_DATA", "/tmp/docscan-bench")) / "barcode" / "synth_dev"
USER_IMAGE = Path(os.environ.get("USER_IMAGE", ""))  # the private photo; required by `user` and run_wasm.py
CPU = os.environ.get("BARCODE_LATENCY_CPU", "3")

# Pre-declared variants (vertical_across, vertical_along, horizontal_across,
# horizontal_along, min_px), all read in the "mosaic" mode (crops packed on
# shared 600 x 800 canvases). Declared after the user's photo showed the first
# margins fall back to the whole frame, before any DEV frame was read.
# Selection on the calibration half: the fewest detection passes among
# variants that lose no full-reading field and add no false field; otherwise
# the fewest lost fields, then false fields, then passes.
# Promotion gate on the held-out half and the user's photo: no lost field and
# no more false fields than the full reading.
VARIANTS = {
    "tight": "0.6,0.15,0.3,0.1,32",
    "medium": "1.0,0.25,0.5,0.2,40",
    "wide": "1.5,0.4,1.0,0.4,48",
}


def norm(s) -> str:
    return "".join(c for c in str(s or "").upper() if c.isalnum())


def probe(paths: list[str], mode: str, *, repeat: int = 1, margins: str | None = None, cpu: str | None = None, parity: bool = False) -> list[dict]:
    cmd = [str(PROBE), f"--models={MODELS}", f"--mode={mode}", f"--repeat={repeat}"]
    if margins:
        cmd.append(f"--margins={margins}")
    if parity:
        cmd.append("--parity")
    if cpu is not None:
        cmd = ["taskset", "-c", cpu] + cmd
    r = subprocess.run(cmd + paths, capture_output=True, text=True, env={**os.environ, "RAYON_NUM_THREADS": "1"}, timeout=1800)
    if r.returncode != 0:
        # stderr can carry a panic message; report only its length.
        raise RuntimeError(f"probe failed ({r.returncode}, {len(r.stderr)} bytes of stderr)")
    return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]


def shard(paths: list[str], mode: str, jobs: int = 2, **kw) -> dict[str, dict]:
    chunks = [paths[i::jobs] for i in range(jobs)]
    with ThreadPoolExecutor(jobs) as ex:
        outs = list(ex.map(lambda c: probe(c, mode, **kw) if c else [], chunks))
    return {o["path"]: o for out in outs for o in out}


def shown(fields: list[dict]) -> list[dict]:
    """What the demo shows: photo.ts drops fields failing their check digit."""
    return [f for f in fields if f.get("check") is not False]


def keys(fields: list[dict]) -> set[tuple]:
    return {(f.get("label"), norm(f.get("value"))) for f in shown(fields)}


def kind_counts(fields: list[dict]) -> dict:
    out: dict[str, int] = {}
    for f in shown(fields):
        out[f["kind"]] = out.get(f["kind"], 0) + 1
    return out


def med(xs):
    return round(statistics.median(xs), 1) if xs else None


MODE = "mosaic"


def compare(base: list[dict], cand: list[dict]) -> dict:
    """Lost / gained readable fields of the candidate against the full
    reading (label and value), and provenance changes of the fields kept: a
    code the full reading confirmed by print (`both`) that the candidate
    reads from bars alone, or the reverse."""
    b, c = keys(base), keys(cand)
    lost = b - c
    kinds = {(f.get("label"), norm(f.get("value"))): f["kind"] for f in shown(base) + shown(cand)}
    by = lambda s: {k: sum(1 for x in s if kinds[x] == k) for k in sorted({kinds[x] for x in s})}
    src = lambda fs: {(f.get("label"), norm(f.get("value"))): f["source"] for f in shown(fs)}
    sb, sc = src(base), src(cand)
    kept = b & c
    return {"base": len(b), "cand": len(c), "lost": len(lost), "gained": len(c - b), "lost_by_kind": by(lost), "gained_by_kind": by(c - b),
            "both_to_barcode": sum(1 for k in kept if sb[k] == "both" and sc[k] != "both"),
            "barcode_to_both": sum(1 for k in kept if sb[k] != "both" and sc[k] == "both"),
            "source_changed": sum(1 for k in kept if sb[k] != sc[k])}


def sums(cmp: list[dict]) -> dict:
    out = {k: sum(c[k] for c in cmp) for k in ("base", "lost", "gained", "both_to_barcode", "barcode_to_both", "source_changed")}
    for key in ("lost_by_kind", "gained_by_kind"):
        agg: dict[str, int] = {}
        for c in cmp:
            for k, n in c[key].items():
                agg[k] = agg.get(k, 0) + n
        out[key] = agg
    return out


def truth_hits(rows: list[dict], res: dict[str, dict]) -> list[tuple[bool, bool]]:
    """Per truth field, in order: (value listed, value listed with its label)."""
    out = []
    for r in rows:
        fields = shown(res[r["path"]]["fields"])
        for f in r["fields"]:
            vals = [g for g in fields if norm(g.get("value")) == norm(f["value"])]
            out.append((bool(vals), any((g.get("label") or None) == (f.get("label") or None) for g in vals)))
    return out


def truth_delta(rows: list[dict], full: dict, cand: dict) -> dict:
    """Truth fields the full reading lists correctly and the candidate does not
    (lost), and the reverse (gained), for value and label+value."""
    a, b = truth_hits(rows, full), truth_hits(rows, cand)
    return {"value_lost": sum(1 for x, y in zip(a, b) if x[0] and not y[0]), "value_gained": sum(1 for x, y in zip(a, b) if y[0] and not x[0]),
            "label_value_lost": sum(1 for x, y in zip(a, b) if x[1] and not y[1]), "label_value_gained": sum(1 for x, y in zip(a, b) if y[1] and not x[1])}


def truth_score(rows: list[dict], res: dict[str, dict]) -> dict:
    """bench/suites/barcode.py's labelled metrics, on the fields the demo shows,
    plus false outputs: shown fields whose value is no truth field or code."""
    n = v = lv = false = 0
    for r in rows:
        fields = shown(res[r["path"]]["fields"])
        truth_vals = {norm(f["value"]) for f in r["fields"]} | {norm(c["text"]) for c in r["codes"]}
        for f in r["fields"]:
            want_v, want_l = norm(f["value"]), (f.get("label") or None)
            vals = [g for g in fields if norm(g.get("value")) == want_v]
            n += 1
            v += bool(vals)
            lv += any((g.get("label") or None) == want_l for g in vals)
        false += sum(1 for g in fields if norm(g.get("value")) not in truth_vals)
    return {"truth_fields": n, "value": round(v / n, 4), "label_value": round(lv / n, 4), "value_hits": v, "label_value_hits": lv, "false_fields": false}


def plan_stats(res: dict[str, dict]) -> dict:
    p = [o["plan"] for o in res.values()]
    return {"frames": len(p), "mean_ocr_share": round(statistics.mean(x["ocr_px"] / x["frame_px"] for x in p), 4),
            "tiles": sum(x["tiles"] for x in p), "detections": sum(o.get("detections") or o["plan"]["tiles"] for o in res.values()),
            "gutter_lines": sum(o.get("gutter_lines") or 0 for o in res.values()), "whole_frame": sum(1 for x in p if x["whole_frame"]),
            "whole_frame_no_bars": sum(1 for x in p if x["whole_frame"] == "NoBars")}


def dev_rows() -> list[dict]:
    rows = [json.loads(l) for l in (DATA / "truth.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("fields")]
    for r in rows:
        r["path"] = str(DATA / r["image"])
    return rows


def write(name: str, obj: dict) -> None:
    (EXP / f"{name}.json").write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
    print(json.dumps(obj, indent=1, sort_keys=True))


def frozen_margins() -> str:
    f = json.loads((EXP / "frozen.json").read_text())
    return VARIANTS[f["variant"]]


def phase_user() -> None:
    if not USER_IMAGE.is_file():
        raise SystemExit("set USER_IMAGE to the private photo")
    img = [str(USER_IMAGE)]
    out: dict = {"image": "user photo (private)", "cpu": CPU}
    # Cold: a fresh process per call (model load reported separately); warm: in process.
    m = frozen_margins() if (EXP / "frozen.json").exists() else VARIANTS["medium"]
    out["margins"] = m
    for mode in ("raw", "full", MODE):
        mm = m if mode == MODE else None
        cold = [probe(img, mode, cpu=CPU, margins=mm, parity=(mode == "full"))[0] for _ in range(3)]
        warm = probe(img, mode, repeat=6, cpu=CPU, margins=mm)[1:]
        o = cold[0]
        out[mode] = {
            "cold_total_ms": [round(c["total_ms"], 1) for c in cold],
            "warm_total_ms_median": med([w["total_ms"] for w in warm]),
            "models_ms_median": med([c.get("models_ms", 0) for c in cold]),
            "decode_jpeg_ms_median": med([c["load_ms"] for c in cold]),
            "warm_stage_ms_median": {k: med([w["stages"][k] for w in warm]) for k in o["stages"]},
            "barcodes": len(o["barcodes"]),
            "barcode_formats": sorted({b["format"] for b in o["barcodes"]}),
        }
        if mode != "raw":
            out[mode].update({"plan": o["plan"], "lines": o["lines"], "detections": o.get("detections"), "gutter_lines": o.get("gutter_lines"), "fields_shown": len(shown(o["fields"])),
                              "fields_check_failed": sum(1 for f in o["fields"] if f.get("check") is False),
                              "kinds_shown": kind_counts(o["fields"]), "labelled_shown": sum(1 for f in shown(o["fields"]) if f.get("label")),
                              "same_as_library": o.get("same_as_library")})
        out[mode]["_fields"] = o.get("fields", [])
    t = [probe(img, MODE, cpu=CPU, margins=VARIANTS["tight"])[0] for _ in range(3)]
    tw = probe(img, MODE, repeat=6, cpu=CPU, margins=VARIANTS["tight"])[1:]
    out["exploratory_tight"] = {"cold_total_ms": [round(c["total_ms"], 1) for c in t], "warm_total_ms_median": med([w["total_ms"] for w in tw]),
                                "warm_stage_ms_median": {k: med([w["stages"][k] for w in tw]) for k in t[0]["stages"]},
                                "plan": t[0]["plan"], "detections": t[0].get("detections"), "kinds_shown": kind_counts(t[0]["fields"]),
                                "vs_full": compare(out["full"]["_fields"], t[0]["fields"])}
    out["candidate_vs_full"] = compare(out["full"]["_fields"], out[MODE]["_fields"])
    for mode in ("raw", "full", MODE):
        del out[mode]["_fields"]
    write("user", out)


def phase_calibrate() -> None:
    rows = dev_rows()[0::2]
    paths = [r["path"] for r in rows]
    full = shard(paths, "full")
    out = {"frames": len(rows), "full": truth_score(rows, full), "variants": {}}
    for name, m in VARIANTS.items():
        roi = shard(paths, MODE, margins=m)
        cmp = [compare(full[p]["fields"], roi[p]["fields"]) for p in paths]
        out["variants"][name] = {"margins": m, **plan_stats(roi), **truth_score(rows, roi), **sums(cmp),
                                 "frames_with_loss": [r["id"] for r, c in zip(rows, cmp) if c["lost"]]}
    ok = [n for n, v in out["variants"].items() if v["lost"] == 0 and v["false_fields"] <= out["full"]["false_fields"]]
    rank = lambda n: (out["variants"][n]["lost"], out["variants"][n]["false_fields"], out["variants"][n]["detections"])
    out["selected"] = min(ok, key=lambda n: out["variants"][n]["detections"]) if ok else min(VARIANTS, key=rank)
    out["selected_rule"] = "fewest detection passes with no lost field and no extra false field; else fewest lost, false, passes"
    write("calibration", out)


def phase_evaluate() -> None:
    rows = dev_rows()
    m = frozen_margins()
    paths = [r["path"] for r in rows]
    full = shard(paths, "full")
    roi = shard(paths, MODE, margins=m)
    out = {"margins": m, "mode": MODE}
    # Exploratory, not promotable: the tight variant as an early preview.
    tight = shard(paths, MODE, margins=VARIANTS["tight"])
    for name, sel in (("held_out_odd", rows[1::2]), ("all_dev", rows)):
        ps = [r["path"] for r in sel]
        cmp = [compare(full[p]["fields"], roi[p]["fields"]) for p in ps]
        tcmp = [compare(full[p]["fields"], tight[p]["fields"]) for p in ps]
        out[name + "_exploratory_tight"] = {**truth_score(sel, tight), **plan_stats({p: tight[p] for p in ps}), **sums(tcmp),
                                            **truth_delta(sel, full, tight)}
        out[name] = {"full": {**truth_score(sel, full), **plan_stats({p: full[p] for p in ps})}, "candidate": {**truth_score(sel, roi), **plan_stats({p: roi[p] for p in ps})},
                     **sums(cmp), **truth_delta(sel, full, roi),
                     "frames_with_loss": [r["id"] for r, c in zip(sel, cmp) if c["lost"]],
                     "frames_with_gain": [r["id"] for r, c in zip(sel, cmp) if c["gained"]]}
    h = out["held_out_odd"]
    out["gate"] = {"rule": "held-out: no lost field and no more false fields than the full reading",
                   "passed": h["lost"] == 0 and h["candidate"]["false_fields"] <= h["full"]["false_fields"]}
    write("evaluation", out)


def phase_latency() -> None:
    rows = dev_rows()[1::2][:12]
    m = frozen_margins()
    paths = [r["path"] for r in rows]
    res = {}
    # Alternate the order across two repeats; one CPU; warm (second iteration).
    for rep in range(2):
        for mode in (("full", MODE) if rep % 2 == 0 else (MODE, "full")):
            for o in probe(paths, mode, repeat=2, margins=m if mode == MODE else None, cpu=CPU):
                if o["iteration"] == 1:
                    res.setdefault(mode, {}).setdefault(o["path"], []).append(o["total_ms"])
    per = {mode: {p: statistics.median(v) for p, v in d.items()} for mode, d in res.items()}
    ratio = [per[MODE][p] / per["full"][p] for p in paths]
    write("latency", {"frames": len(paths), "cpu": CPU, "full_ms_median": med(list(per["full"].values())),
                      "candidate_ms_median": med(list(per[MODE].values())), "candidate_ms_max": round(max(per[MODE].values()), 1), "full_ms_max": round(max(per["full"].values()), 1), "roi_over_full_median": round(statistics.median(ratio), 3),
                      "roi_over_full_max": round(max(ratio), 3)})


def phase_freeze() -> None:
    sel = json.loads((EXP / "calibration.json").read_text())["selected"]
    if (EXP / "frozen.json").exists():
        raise SystemExit("frozen.json exists: the candidate is frozen")
    write("frozen", {"variant": sel, "margins": VARIANTS[sel], "mode": MODE, "probe_sha256": sha(PROBE)})


def sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


if __name__ == "__main__":
    {"freeze": phase_freeze, "user": phase_user, "calibrate": phase_calibrate, "evaluate": phase_evaluate, "latency": phase_latency}[sys.argv[1]]()
