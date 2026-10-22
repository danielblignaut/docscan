"""The bench's proof-of-address DEV scoring for a change that does not touch
OCR (the tagger, its features, voting, verification), without OCR'ing the
800 frames again: the frames' OCR words come from a bench run's own cache
(`$BENCH_DATA/cache/poa_ocr/<key>.jsonl`), and the capture stage and scoring
are bench/suites/poa.py's own functions, run with the given poa_capture
binary and tagger.

Writes a result JSON shaped like the bench's (the reference run's meta, the
poa.dev metrics replaced), so `bench/compare.py <reference> <this>` judges it.
The bench itself remains the referee: a change is measured by
`bench/run.sh --suite poa` before it is pushed.

  python train/dev_capture_eval.py --reference bench/results/<ref>.json --ocr-cache /tmp/docscan-bench/cache/poa_ocr/<key>.jsonl \
      --capture-bin /tmp/docscan-poa-work/target/release/examples/poa_capture --tagger /tmp/docscan-poa-work/models/m1/poa-tagger.onnx \
      --out /tmp/docscan-poa-work/results/m1.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
from lib.common import env1, sha256_file  # noqa: E402
from suites import poa as P  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", help="a bench result whose meta to copy (for bench/compare.py); else see train/cmp.py")
    ap.add_argument("--ocr-cache", required=True)
    ap.add_argument("--capture-bin", required=True)
    ap.add_argument("--tagger", required=True)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--extra", nargs="*", default=[], help="extra poa_capture arguments")
    args = ap.parse_args()
    cache = {}
    for line in Path(args.ocr_cache).read_text().splitlines():
        k, v = json.loads(line)
        cache[k] = v
    _, caps, truths = P.captures("poa_dev", args.quick)
    pages = {}
    for c in caps:
        for f in c["frames"]:
            pages[f["path"]] = cache[sha256_file(Path(f["path"]))]
    lines = []
    for c in caps:
        fr = [pages[f["path"]] for f in c["frames"]]
        lines.append(json.dumps({"id": c["id"], "customer": truths[c["id"]]["customer"], "frames": [
            {k: f.get(k) for k in ("words", "page_size", "page", "error", "fallback")} for f in fr]}))
    r = subprocess.run([args.capture_bin, f"--today={P.TODAY}", f"--tagger={args.tagger}", *args.extra], input="\n".join(lines),
                       capture_output=True, text=True, env=env1())
    if r.returncode:
        raise SystemExit(r.stderr[-3000:])
    out = {d["id"]: d for d in (json.loads(x) for x in r.stdout.splitlines() if x.strip())}
    metrics = P.score("dev", caps, truths, out)
    ref = json.loads(Path(args.reference).read_text()) if args.reference else {"meta": {}, "metrics": {}}
    res = {**ref, "metrics": {**{k: v for k, v in ref["metrics"].items() if not k.startswith("poa.")}, **metrics}}
    res["meta"] = {**ref["meta"], "note": f"dev_capture_eval: tagger {args.tagger}, {args.capture_bin}"}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res))
    show = ["genuine_accept", "key_fields", "reject_wrong_person", "reject_wrong_address", "reject_old", "reject_issuer_decoy"]
    print(" ".join(f"{k}={100 * metrics[f'poa.dev.{k}']['value']:.1f}" for k in show),
          "| single key", f"{100 * metrics['poa.dev.single.key_fields']['value']:.1f}",
          "| frames", metrics["poa.dev.frames_read_mean"]["value"],
          "|", " ".join(f"{f}={100 * metrics[f'poa.dev.field.{f}']['value']:.0f}" for f in P.FIELDS))


if __name__ == "__main__":
    main()
