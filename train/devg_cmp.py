"""Paired comparison of two train/devg_eval.py --json outputs (same pages):
per field and for key fields and genuine acceptance, B - A with a paired
bootstrap 95% interval.

  python train/devg_cmp.py A.json B.json
"""
import json
import sys

import numpy as np

a, b = (json.load(open(p)) for p in sys.argv[1:3])
ra = {r["id"]: r for r in a["rows"]}
rb = {r["id"]: r for r in b["rows"]}
ids = sorted(set(ra) & set(rb))
rng = np.random.default_rng(0)


def show(name, xa, xb):
    xa, xb = np.array(xa, float), np.array(xb, float)
    d = xb - xa
    boots = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    flag = "  BETTER" if lo > 0 else ("  WORSE" if hi < 0 else "")
    print(f"{name:16s} {100 * xa.mean():6.1f} -> {100 * xb.mean():6.1f}  {100 * d.mean():+6.1f} [{100 * lo:+.1f}, {100 * hi:+.1f}]{flag}")


show("key_fields", [ra[i]["key"] for i in ids], [rb[i]["key"] for i in ids])
for f in ra[ids[0]]["right"]:
    show(f, [ra[i]["right"][f] for i in ids], [rb[i]["right"][f] for i in ids])
gen = [i for i in ids if ra[i].get("reasons") is not None]
show("accepted(all)", [ra[i]["accepted"] for i in ids], [rb[i]["accepted"] for i in ids])
