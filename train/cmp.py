"""Paired comparison of the poa rate metrics of two result JSONs (bench's or
train/dev_capture_eval.py's), with bench/compare.py's own paired bootstrap:
for quick looks between bench runs. bench/compare.py stays the referee.

  python train/cmp.py A.json B.json [--prefix poa.dev]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
from compare import compare_rate  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("a")
ap.add_argument("b")
ap.add_argument("--prefix", default="poa.dev")
args = ap.parse_args()
A, B = (json.loads(Path(p).read_text())["metrics"] for p in (args.a, args.b))
for k in A:
    if not k.startswith(args.prefix) or k not in B or A[k]["kind"] != "rate":
        continue
    d, lo, hi, how = compare_rate(A[k], B[k])
    flag = "  BETTER" if lo > 0 else ("  WORSE" if hi < 0 else "")
    print(f"{k:45s} {100 * A[k]['value']:6.1f} -> {100 * B[k]['value']:6.1f}  {100 * d:+6.1f} [{100 * lo:+.1f}, {100 * hi:+.1f}]{flag}")
