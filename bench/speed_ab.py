"""Interleaved A/B timing: the reference build and this build, alternately, on
the same pinned core, in one session.

  python bench/speed_ab.py [--ref SHA] [--suite id,barcode,poa,face] [--repeats N] [--quick] [--out FILE]

Two full runs measured hours apart on this shared machine differ by 25-35%
in raw speed and their calibration job is bimodal (bench/noise.json, BASELINE.md),
so compare.py can only catch large speed changes between runs. A speed claim
of a few percent needs both builds timed under the same load: this script
builds the reference commit (default: the baseline's) in its own worktree
under $BENCH_DATA/ref/ with its own target directory, then for every repeat
runs each suite's native timing pass once with the reference binaries and
once with this worktree's, alternating which goes first, and judges the
per-item ratios this/reference pooled over all repeats.

Verdict per metric: the median per-item ratio with a bootstrap 95% interval;
a regression when it is above 1.05 with the interval wholly above 1 (the
regression rule's 5%), an improvement below 0.95 with the interval wholly
below 1. Exit status 1 on any regression.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import common, stats  # noqa: E402
from lib.common import DATA, ROOT, log  # noqa: E402

BASELINE_SHA = "c437ffa"


def git(*a, cwd=ROOT) -> str:
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def build_ref(sha: str) -> Path:
    """The reference commit's release examples, built in a worktree of its own."""
    full = git("rev-parse", sha)
    wt = DATA / "ref" / full[:12]
    if not (wt / ".git").exists():
        wt.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "worktree", "add", "--detach", str(wt), full], cwd=ROOT, check=True)
    # Models are fetched, not committed: the reference reads them from its own tree.
    for m in (ROOT / "models").glob("*.rten"):
        dst = wt / "models" / m.name
        if not dst.exists():
            dst.write_bytes(m.read_bytes())
    target = DATA / "ref" / f"target-{full[:12]}"
    log(f"building the reference {full[:10]} in {wt}")
    subprocess.run(["cargo", "build", "--release", "--examples", "--quiet"], cwd=wt / "docscan", check=True,
                   env={**os.environ, "CARGO_TARGET_DIR": str(target)})
    return target / "release" / "examples"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default=BASELINE_SHA)
    ap.add_argument("--suite", default="id,barcode,poa,face")
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    ref_bin = build_ref(a.ref)
    subprocess.run(["cargo", "build", "--release", "--examples", "--quiet"], cwd=ROOT / "docscan", check=True)
    new_bin = common.BIN
    import bench

    ctx = bench.Ctx(splits=["dev"], quick=a.quick, jobs=common.JOBS, repeats=1, speed_only=True)
    samples: dict[str, dict[str, dict[str, list[float]]]] = {}  # metric -> side -> item -> [ms]
    load0 = common.loadavg()
    for r in range(a.repeats):
        order = [("ref", ref_bin), ("new", new_bin)] if r % 2 == 0 else [("new", new_bin), ("ref", ref_bin)]
        for side, b in order:
            common.BIN = b
            for su in a.suite.split(","):
                mod = importlib.import_module(f"suites.{su}")
                for k, m in mod.run(ctx).items():
                    if m["kind"] != "latency":
                        continue
                    per = samples.setdefault(k, {}).setdefault(side, {})
                    for i, v in zip(m["ids"], m["samples"]):
                        per.setdefault(i, []).append(v)
            log(f"repeat {r + 1}/{a.repeats}: {side} done")
    common.BIN = new_bin
    rows, regress = [], []
    out = {"ref": git("rev-parse", a.ref), "new": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain")),
           "repeats": a.repeats, "load_start": load0, "load_end": common.loadavg(),
           "timestamp_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "metrics": {}}
    for k, sides in samples.items():
        items = [i for i in sides.get("ref", {}) if i in sides.get("new", {})]
        if not items:
            continue
        # Pair each repeat's new with the same repeat's reference, per item.
        ratios = [n / max(rf, 1e-9) for i in items for n, rf in zip(sides["new"][i], sides["ref"][i])]
        rr = np.array(ratios)
        rng = np.random.default_rng(0)
        meds = np.median(rr[rng.integers(0, len(rr), size=(2000, len(rr)))], axis=1)
        med, lo, hi = float(np.median(rr)), float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))
        status = "REGRESSED" if med > 1.05 and lo > 1 else "improved" if med < 0.95 and hi < 1 else "same"
        if status == "REGRESSED":
            regress.append(k)
        ref_med = float(np.median([v for i in items for v in sides["ref"][i]]))
        new_med = float(np.median([v for i in items for v in sides["new"][i]]))
        out["metrics"][k] = {"ratio": med, "ci95": [lo, hi], "ref_ms": ref_med, "new_ms": new_med, "pairs": len(ratios), "status": status}
        rows.append((k, f"{ref_med:.0f}", f"{new_med:.0f}", f"{100 * (med - 1):+.1f}%", f"[{100 * (lo - 1):+.1f}%, {100 * (hi - 1):+.1f}%]", status))
    w = [max(len(str(r[i])) for r in rows + [("metric", "ref ms", "new ms", "delta", "95% CI", "status")]) for i in range(6)]
    for r in [("metric", "ref ms", "new ms", "delta", "95% CI", "status")] + rows:
        print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))
    print(f"\nload {out['load_start']} -> {out['load_end']}; verdict: {'regressed' if regress else 'no speed regression'}")
    path = Path(a.out) if a.out else common.BENCH / "results" / f"speedab-{out['new'][:10]}-vs-{out['ref'][:10]}-{out['timestamp_utc'].replace(':', '').replace('-', '')}.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(path)
    sys.exit(1 if regress else 0)


if __name__ == "__main__":
    main()
