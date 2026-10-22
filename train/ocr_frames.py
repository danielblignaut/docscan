"""OCR the DEV capture frames with a given `examples/poa` binary (and
environment), into a file in the bench's OCR-cache format, for
train/dev_capture_eval.py: to try an OCR change on DEV (`--quick`: the bench's
own quick subset) without a full bench run.

  python train/ocr_frames.py --bin /tmp/docscan-poa-work/target/release/examples/poa --quick --jobs 2 \
      --env DOCSCAN_DET_MODEL=/tmp/docscan-poa-work/text-detection-page.onnx --out /tmp/docscan-poa-work/ocr/page_q.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
from lib.common import run_jsonl_sharded, sha256_file  # noqa: E402
from suites import poa as P  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--env", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--glob", help="OCR these images instead of the DEV frames (records keep their `path`)")
    args = ap.parse_args()
    for kv in args.env:
        k, v = kv.split("=", 1)
        os.environ[k] = v
    if args.glob:
        import glob as g
        paths = sorted(g.glob(args.glob))
    else:
        _, caps, _ = P.captures("poa_dev", args.quick)
        paths = [f["path"] for c in caps for f in c["frames"]]
    shas = {p: sha256_file(Path(p)) for p in paths}
    done = {}
    out = Path(args.out)
    if out.exists():
        for line in out.read_text().splitlines():
            k, v = json.loads(line)
            done[k] = v
    todo = [p for p in paths if shas[p] not in done]
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "a") as f:
        for r in run_jsonl_sharded([args.bin, "--words"], todo, args.jobs):
            f.write(json.dumps([shas[r["path"]], {k: r.get(k) for k in (*P.KEEP, "path")}]) + "\n")
            f.flush()
    print(f"{len(todo)} frames OCR'd, {len(paths) - len(todo)} already done -> {out}")


if __name__ == "__main__":
    main()
