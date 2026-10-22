"""Score a tagger on DEV-G: pages of held-out layout families, fonts, people,
streets and places (testdata/poa_wide.py --split devg), one camera frame
each, OCR'd by train/build_dataset.py.

Blind extraction (key fields: holder, street, city, postal code and date all
right, as eval/poa_eval.py scores them) and verification against the known
customer: the page's own holder (genuine) and two negatives per page made
from it (another surname; another house number).

  python train/devg_eval.py --pages /tmp/docscan-poa-work/ds/devg_camera.jsonl --truth /tmp/docscan-poa-work/devg \
      --tagger models/poa-tagger.onnx [--bin docscan/target/release/examples]
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
from poa_eval import FIELDS, KEY, correct, flatten  # noqa: E402


def customer(truth: dict) -> dict:
    p = truth["person"]
    a = truth["fields"]["address"]
    given = " ".join(x for x in (p["first"], p.get("middle")) if x)
    return {"name": f"{given} {p['surname']}".upper(), "surname": p["surname"].upper(),
            "address": {k: a[k] for k in ("street", "suburb", "city", "postal_code")}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--tagger", required=True)
    ap.add_argument("--bin", default=str(ROOT / "docscan" / "target" / "release" / "examples"))
    ap.add_argument("--today", default="2026-10-15")
    ap.add_argument("--json", help="write the per-page outcomes here")
    ap.add_argument("--captures", help="a directory of poa_capture.py bursts (<id>.json): score captures of up to four frames, "
                                       "the frames' OCR read from --pages (lines with `path` and `words`, e.g. train/ocr_frames.py output)")
    args = ap.parse_args()
    if args.captures:
        by_path = {}
        for p in args.pages:
            for line in open(p):
                r = json.loads(line)
                if isinstance(r, list):  # train/ocr_frames.py: [sha, record]
                    r = r[1]
                by_path[r.get("path")] = r
        pages = []
        for cj in sorted(Path(args.captures).glob("poa_*.json")):
            c = json.loads(cj.read_text())
            frames = []
            for f in c["frames"]:
                r = by_path.get(f["image"]) or {}
                frames.append({k: r.get(k) for k in ("words", "page_size", "page", "error", "fallback")})
            pages.append({"id": c["id"], "frames": frames})
    else:
        pages = [json.loads(line) for p in args.pages for line in open(p)]
    truths = {p["id"]: json.loads((Path(args.truth) / f"{p['id']}.json").read_text()) for p in pages}
    rng = random.Random(5)
    surnames = sorted({t["person"]["surname"] for t in truths.values()})
    lines, cases = [], {}
    for p in pages:
        t = truths[p["id"]]
        frames = p["frames"] if "frames" in p else [{"words": p.get("words") if p.get("ok") else None, "page_size": p.get("page_size"), "page": {"accepted": True}}]
        c = customer(t)
        lines.append(json.dumps({"id": p["id"] + ":g", "customer": c, "frames": frames}))
        # The holder's own page, accepted only when dated within three months.
        cases[p["id"] + ":g"] = ("genuine" if t["recent"] and not t["future_dated"] else "old", p, t)
        wp = json.loads(json.dumps(c))
        other = rng.choice([s for s in surnames if s.upper() != c["surname"]])
        wp["name"] = c["name"][: -len(c["surname"])].strip() + " " + other.upper()
        wp["surname"] = other.upper()
        lines.append(json.dumps({"id": p["id"] + ":p", "customer": wp, "frames": frames}))
        cases[p["id"] + ":p"] = ("wrong_person", p, t)
        wa = json.loads(json.dumps(c))
        num, rest = wa["address"]["street"].split(" ", 1)
        digits = "".join(ch for ch in num if ch.isdigit())
        wa["address"]["street"] = f"{int(digits) + rng.randint(1, 9)} {rest}"
        lines.append(json.dumps({"id": p["id"] + ":a", "customer": wa, "frames": frames}))
        cases[p["id"] + ":a"] = ("wrong_address", p, t)
    one = [] if args.captures else ["--max-frames=1", "--min-frames=1"]
    r = subprocess.run([f"{args.bin}/poa_capture", f"--today={args.today}", f"--tagger={args.tagger}", *one],
                       input="\n".join(lines), capture_output=True, text=True, env={"RAYON_NUM_THREADS": "1", "RTEN_NUM_THREADS": "1", "PATH": "/usr/bin"})
    if r.returncode:
        sys.exit(r.stderr[-3000:])
    out = {d["id"]: d for d in (json.loads(x) for x in r.stdout.splitlines() if x.strip())}
    ver = defaultdict(list)
    key, fld = [], defaultdict(list)
    by_layout = defaultdict(list)
    rows = []
    for cid, (case, p, t) in cases.items():
        res = out[cid]["capture"]
        acc = bool((res.get("verify") or {}).get("accepted"))
        ver[case].append(acc == (case == "genuine"))
        if case not in ("genuine", "old"):
            continue
        pred, truth = flatten(res.get("fields")), flatten(t["fields"])
        right = {f: correct(f, pred.get(f), truth[f]) for f in FIELDS}
        k = all(right[f] for f in KEY)
        key.append(k)
        fam = t["layout"].split("_")[0] + "_" + t["layout"].split("_")[1] if t["layout"].startswith("w_") else "proc"
        by_layout[fam].append(k)
        for f in FIELDS:
            fld[f].append(right[f])
        rows.append({"id": p["id"], "layout": t["layout"], "key": k, "accepted": acc, "right": right,
                     "pred": {f: pred.get(f) for f in FIELDS}, "truth": {f: truth[f] for f in FIELDS},
                     "reasons": (res.get("verify") or {}).get("reasons")})
    pct = lambda v: f"{100 * sum(v) / max(1, len(v)):.1f}%"  # noqa: E731
    summary = {"pages": len(key), "key_fields": pct(key), **{f: pct(v) for f, v in fld.items()},
               "genuine_accept": pct(ver["genuine"]), "reject_wrong_person": pct(ver["wrong_person"]),
               "reject_wrong_address": pct(ver["wrong_address"]), "reject_old": pct(ver["old"]), "by_family": {k: f"{pct(v)} of {len(v)}" for k, v in sorted(by_layout.items())}}
    print(json.dumps(summary, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
