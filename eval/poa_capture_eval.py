"""Score proof-of-address reading per capture (a burst of camera frames, as the
live capture sees) and per single frame, for the DEV set and the lockbox.

  # 1. OCR every frame once (slow; cached): page analysis, outline, OCR words
  python eval/poa_capture_eval.py ocr --set /tmp/docscan-poa/dev
  # 2. Score (fast, from the cache): verification against the known customer and blind extraction
  python eval/poa_capture_eval.py score --set /tmp/docscan-poa/dev [--tagger models/poa-tagger.onnx] [--json out.json]

A set directory holds docs/<id>.json (truth with `case` and `customer`, from
testdata/poa_dev_claims.py or poa_lockbox.py) and frames/<id>.json (the
capture, from testdata/poa_capture.py). The OCR cache is <set>/ocr.jsonl.

Verification: a genuine capture must be accepted, every negative rejected.
Blind extraction: name, street, city, postal code and date all right (as
eval/poa_eval.py scores a field: upper-cased, letters and digits only; dates
as ISO), over every document.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "docscan" / "target" / "release" / "examples"
sys.path.insert(0, str(ROOT / "eval"))
from poa_eval import FIELDS, KEY, correct, flatten  # noqa: E402

CASES = ["genuine", "wrong_person", "wrong_address", "old", "issuer_decoy"]


def corner_error(found, truth, frame) -> float:
    diag = (frame[0] ** 2 + frame[1] ** 2) ** 0.5
    return max(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(found, truth)) / diag


def cmd_ocr(args):
    s = Path(args.set)
    caps = [json.loads(p.read_text()) for p in sorted((s / "frames").glob("*.json"))]
    frames = [(c["id"], k, f) for c in caps for k, f in enumerate(c["frames"])]
    cache = s / "ocr.jsonl"
    done = set()
    if cache.exists() and not args.redo:
        for line in cache.read_text().splitlines():
            r = json.loads(line)
            done.add((r["id"], r["k"]))
    todo = [x for x in frames if (x[0], x[1]) not in done]
    print(f"{len(frames)} frames, {len(todo)} to OCR", flush=True)
    jobs = args.jobs
    chunks = [todo[i::jobs] for i in range(jobs)]
    env = {**os.environ, "RAYON_NUM_THREADS": "1"}
    extra = args.extra.split() if args.extra else []

    def one(chunk):
        if not chunk:
            return []
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("\n".join(x[2]["image"] for x in chunk))
        res = subprocess.run([str(BIN / "poa"), "--words", *extra, f"@{f.name}"], capture_output=True, text=True, env=env)
        os.unlink(f.name)
        if res.returncode:
            sys.stderr.write(res.stderr)
        by_path = {}
        for line in res.stdout.splitlines():
            if line.strip():
                r = json.loads(line)
                by_path[r["path"]] = r
        out = []
        for cid, k, fr in chunk:
            r = by_path.get(fr["image"], {"error": "missing"})
            rec = {"id": cid, "k": k, "page": r.get("page"), "error": r.get("error"), "fallback": r.get("fallback", False)}
            if "corners" in r:
                rec["corners"] = r["corners"]
                rec["corner_error"] = round(corner_error(r["corners"], fr["corners_tl_tr_br_bl"], fr["frame"]), 4)
            for key in ("words", "page_size", "ms"):
                if key in r:
                    rec[key] = r[key]
            out.append(rec)
        return out

    mode = "w" if args.redo else "a"
    with open(cache, mode) as f, ThreadPoolExecutor(jobs) as ex:
        for part in ex.map(one, chunks):
            for rec in part:
                f.write(json.dumps(rec) + "\n")
    print(f"-> {cache}")


def load_set(s: Path):
    truths = {p.stem: json.loads(p.read_text()) for p in sorted((s / "docs").glob("*.json"))}
    frames = defaultdict(dict)
    for line in (s / "ocr.jsonl").read_text().splitlines():
        r = json.loads(line)
        frames[r["id"]][r["k"]] = r
    return truths, frames


def run_capture_bin(truths, frames, args) -> dict:
    """Feeds every capture to the Rust capture pipeline (examples/poa_capture.rs)."""
    lines = []
    for cid, t in truths.items():
        fr = [frames[cid][k] for k in sorted(frames[cid])]
        lines.append(json.dumps({"id": cid, "customer": t["customer"], "frames": [
            {k: f.get(k) for k in ("words", "page_size", "page", "error", "fallback")} for f in fr]}))
    cmd = [str(BIN / "poa_capture"), f"--today={args.today}"]
    if args.tagger:
        cmd.append(f"--tagger={args.tagger}")
    cmd += args.opt or []
    res = subprocess.run(cmd, input="\n".join(lines), capture_output=True, text=True)
    if res.returncode:
        sys.exit(res.stderr)
    return {r["id"]: r for r in (json.loads(x) for x in res.stdout.splitlines() if x.strip())}


def pct(a, b) -> str:
    return f"{100 * a / max(1, b):.1f}% ({a}/{b})"


def cmd_score(args):
    s = Path(args.set)
    truths, frames = load_set(s)
    out = run_capture_bin(truths, frames, args)
    report = {}
    for mode in ("capture", "single"):
        ver = Counter()
        n_case = Counter()
        field_ok = Counter()
        key_ok = 0
        n = 0
        errors = defaultdict(list)
        for cid, t in truths.items():
            r = out[cid]
            results = [r["capture"]] if mode == "capture" else r["frames"]
            for res in results:
                n += 1
                case = t["case"]
                n_case[case] += 1
                accepted = bool(res.get("verify", {}).get("accepted"))
                ok = accepted == t["expect_accept"]
                ver[case] += ok
                if not ok and mode == "capture":
                    errors[case].append((cid, res.get("verify", {}).get("reasons")))
                pred = flatten(res.get("fields"))
                truth = flatten(t["fields"])
                right = {f: correct(f, pred.get(f), truth[f]) for f in FIELDS}
                for f in FIELDS:
                    field_ok[f] += right[f]
                key_ok += all(right[f] for f in KEY)
                if mode == "capture" and not all(right[f] for f in KEY):
                    errors["blind"].append((cid, {f: (pred.get(f), truth[f]) for f in KEY if not right[f]}))
        rep = {"n": n, "verification": {c: ver[c] / max(1, n_case[c]) for c in CASES},
               "verification_counts": {c: [ver[c], n_case[c]] for c in CASES},
               "true_reject_all": sum(ver[c] for c in CASES[1:]) / max(1, sum(n_case[c] for c in CASES[1:])),
               "fields": {f: field_ok[f] / n for f in FIELDS}, "key_fields": key_ok / n}
        report[mode] = rep
        print(f"\n== {s.name} · per {mode} ({n}) ==")
        print("verification: " + ", ".join(f"{c} {pct(ver[c], n_case[c])}" for c in CASES))
        print(f"blind key fields: {pct(key_ok, n)}; " + ", ".join(f"{f} {100 * field_ok[f] / n:.0f}%" for f in FIELDS))
        if mode == "capture" and args.errors:
            for case, errs in errors.items():
                print(f"-- {case} errors ({len(errs)}):")
                for e in errs[: args.errors]:
                    print("  ", e)
    caps = [out[c]["capture"] for c in truths]
    ocrd = [x.get("frames_read", 0) for x in caps]
    fb = sum(1 for x in caps if x.get("fallback"))
    print(f"\nframes read per capture: mean {sum(ocrd) / len(ocrd):.2f}; captures on the guide-crop fallback: {fb}")
    report["frames_read_mean"] = sum(ocrd) / len(ocrd)
    report["fallback_captures"] = fb
    if args.json:
        Path(args.json).write_text(json.dumps({"report": report, "results": out}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("ocr")
    o.add_argument("--set", required=True)
    o.add_argument("--jobs", type=int, default=10)
    o.add_argument("--redo", action="store_true")
    o.add_argument("--extra", help="extra arguments for examples/poa")
    sc = sub.add_parser("score")
    sc.add_argument("--set", required=True)
    sc.add_argument("--tagger", default=str(ROOT / "models" / "poa-tagger.onnx"))
    sc.add_argument("--today", default="2026-10-15")
    sc.add_argument("--json")
    sc.add_argument("--errors", type=int, default=0, help="print this many errors per class")
    sc.add_argument("--opt", nargs="*", help="options passed to examples/poa_capture")
    args = ap.parse_args()
    {"ocr": cmd_ocr, "score": cmd_score}[args.cmd](args)


if __name__ == "__main__":
    main()
