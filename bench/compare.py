"""Compare two benchmark results: per-metric deltas with significance, and a verdict.

  python bench/compare.py A.json B.json [--only PREFIX ...] [--all] [--accept-tradeoff] [--noise bench/noise.json]

A is the reference (usually the baseline or the parent commit), B the change.

- Accuracy-type metrics (rates and statistics such as TAR @ FAR, AUC, 10-fold
  accuracy): B - A with a **paired** bootstrap 95% interval over the same items
  (2 000 resamples for rates, 500 for statistics, stratified by label and
  fold). A change is significant when the interval excludes 0 *and* the delta
  is beyond twice the metric's measured run-to-run noise (bench/noise.json,
  one difference between two baseline runs; 0 for deterministic metrics).
- Latencies: the median of per-item ratios B/A with a bootstrap 95% interval,
  divided by the ratio of a fixed calibration job timed on the same core in
  each run (so a busier machine is not read as a slower scanner), the medians
  with IQR, and a two-sided Mann-Whitney p of the raw samples. A speed
  regression is a calibrated ratio above 1 + max(5%, 2 x noise) whose
  interval lies wholly above 1.
- Verdict: **regressed** if any accuracy metric is significantly worse, or any
  speed metric regresses beyond 5% (unless --accept-tradeoff is given *and*
  some accuracy metric improved significantly: the gain must be explicit);
  **improved** if something improved significantly and nothing regressed;
  otherwise **no change**. Exit status 1 when regressed.

Metrics on different item sets (a --quick run against a full one, a changed
manifest) are compared on the shared items where possible and flagged; a
changed referee (bench code hash) or dataset (manifest hash) is warned about
loudly, because then A and B were not measured the same way.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import stats  # noqa: E402

TTY = sys.stdout.isatty()
RED, GREEN, YELLOW, BOLD, DIM, END = ("\033[31m", "\033[32m", "\033[33m", "\033[1m", "\033[2m", "\033[0m") if TTY else ("",) * 6
SPEED_TOLERANCE = 0.05
# bench/noise.json holds one difference between two runs of the same code: a
# single draw of the noise, so the margin is twice that.
NOISE_MULT = 2.0


def load(p: str) -> dict:
    return json.loads(Path(p).read_text())


def pct(v: float) -> str:
    return f"{100 * v:+.2f} pt"


def fmt_val(m: dict) -> str:
    v = m["value"]
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    if m.get("unit") == "%":
        return f"{100 * v:.2f}%"
    if m.get("unit") in ("ms", "s"):
        return f"{v:.4g} {m['unit']}"
    return f"{v:.4g}"


def compare_rate(a: dict, b: dict):
    if a["ids"] == b["ids"]:
        oa, ob = [int(c) for c in a["ok"]], [int(c) for c in b["ok"]]
        d, lo, hi = stats.paired_bootstrap_rate(oa, ob)
        return d, lo, hi, "paired"
    ia = dict(zip(a["ids"], a["ok"]))
    ib = dict(zip(b["ids"], b["ok"]))
    shared = [k for k in a["ids"] if k in ib]
    if len(shared) >= 0.5 * min(len(ia), len(ib)) and shared:
        d, lo, hi = stats.paired_bootstrap_rate([int(ia[k]) for k in shared], [int(ib[k]) for k in shared])
        return d, lo, hi, f"paired on {len(shared)} shared items"
    d, lo, hi = stats.unpaired_bootstrap_rate([int(c) for c in a["ok"]], [int(c) for c in b["ok"]])
    return d, lo, hi, "unpaired (different items)"


def compare_stat(a: dict, b: dict):
    ra, rb = a["raw"], b["raw"]
    same_items = a.get("ids_sha256") == b.get("ids_sha256") and ra["labels"] == rb["labels"] and ra.get("folds") == rb.get("folds")
    if not same_items:
        return None, None, None, "different items: not compared"
    d, lo, hi = stats.paired_bootstrap_stat(a["stat"], ra, rb, a["params"], b["params"], b=500)
    return d, lo, hi, "paired"


def compare_latency(a: dict, b: dict):
    """Median per-item ratio B/A with its bootstrap interval, divided by the
    ratio of the calibration job's times (the core's speed at each run) when
    both runs recorded one; and the Mann-Whitney p of the raw samples."""
    ia = dict(zip(a["ids"], a["samples"]))
    ib = dict(zip(b["ids"], b["samples"]))
    shared = [k for k in a["ids"] if k in ib]
    _, p = stats.mann_whitney(a["samples"], b["samples"])
    k, note = 1.0, ""
    if a.get("calib_ms") and b.get("calib_ms"):
        k = b["calib_ms"] / a["calib_ms"]
        note = f"; machine x{k:.2f}, calibrated"
    if shared:
        r, lo, hi = stats.paired_latency_ratio([ia[i] for i in shared], [ib[i] for i in shared])
        return r / k, lo / k, hi / k, p, f"paired ratio on {len(shared)} items{note}"
    ma, mb = np.median(a["samples"]), np.median(b["samples"])
    return mb / ma / k, float("nan"), float("nan"), p, "unpaired" + note


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--only", nargs="*", help="metric name prefixes to compare")
    ap.add_argument("--all", action="store_true", help="also list unchanged metrics")
    ap.add_argument("--accept-tradeoff", action="store_true", help="a speed regression is accepted when some accuracy metric improved significantly")
    ap.add_argument("--noise", default=str(Path(__file__).resolve().parent / "noise.json"))
    args = ap.parse_args()
    A, B = load(args.a), load(args.b)
    noise = json.loads(Path(args.noise).read_text()) if Path(args.noise).exists() else {}

    warnings = []
    ma, mb = A["meta"], B["meta"]
    if ma.get("bench_code_sha256") != mb.get("bench_code_sha256"):
        warnings.append("the referee changed: bench code differs between A and B (bench_code_sha256); a scanner change must not be judged by a changed scorer")
    for s in set(ma.get("manifests", {})) & set(mb.get("manifests", {})):
        if ma["manifests"][s]["tree_sha256"] != mb["manifests"][s]["tree_sha256"]:
            warnings.append(f"dataset {s} differs between A and B (manifest hash): its metrics are not comparable")
    if ma["args"].get("quick") != mb["args"].get("quick"):
        warnings.append("one run is --quick and the other is not: only shared items are compared")
    la, lb = (ma.get("load_start") or [0])[0], (mb.get("load_start") or [0])[0]
    if max(la, lb) > 2 * max(1.0, min(la, lb)) and abs(la - lb) > 4:
        warnings.append(f"the machine's load differed (1-min load {la} vs {lb}): latencies are calibrated against a fixed job on the same core, "
                        "but contention is not linear; recheck a speed verdict at similar load")
    if mb.get("git_dirty"):
        warnings.append(f"B was run with uncommitted changes ({len(mb['git_dirty'])} files)")
    print(f"A: {ma['git_sha'][:10]} {ma['timestamp_utc']} load {ma.get('load_start')}  {'quick' if ma['args'].get('quick') else 'full'}")
    print(f"B: {mb['git_sha'][:10]} {mb['timestamp_utc']} load {mb.get('load_start')}  {'quick' if mb['args'].get('quick') else 'full'}")
    for w in warnings:
        print(f"{YELLOW}{BOLD}WARNING{END}{YELLOW}: {w}{END}")
    print()

    rows, regress_acc, regress_speed, improve_acc, improve_speed = [], [], [], [], []
    names = [k for k in A["metrics"] if k in B["metrics"]]
    if args.only:
        names = [k for k in names if any(k.startswith(p) for p in args.only)]
    for k in names:
        a, b = A["metrics"][k], B["metrics"][k]
        if a["kind"] != b["kind"] or a["kind"] == "info":
            continue
        nf = NOISE_MULT * float(noise.get(k, 0.0) or 0.0)
        better = a.get("better", "higher")
        if a["kind"] in ("rate", "stat"):
            d, lo, hi, how = compare_rate(a, b) if a["kind"] == "rate" else compare_stat(a, b)
            if d is None:
                rows.append((k, fmt_val(a), fmt_val(b), "", "", how, "n/a"))
                continue
            sig = (lo > 0 or hi < 0) and abs(d) > nf
            good = (d > 0) == (better == "higher")
            status = ("improved" if good else "REGRESSED") if sig else "same"
            (improve_acc if status == "improved" else regress_acc if status == "REGRESSED" else []).append(k)
            ci = f"[{100 * lo:+.2f}, {100 * hi:+.2f}]" if a.get("unit") == "%" else f"[{lo:+.4f}, {hi:+.4f}]"
            delta = pct(d) if a.get("unit") == "%" else f"{d:+.4f}"
            rows.append((k, fmt_val(a), fmt_val(b), delta, ci, how, status))
        else:
            r, lo, hi, p, how = compare_latency(a, b)
            tol = max(SPEED_TOLERANCE, nf)
            if r > 1 + tol and (lo > 1 or (math.isnan(lo) and p < 0.05)):
                status = "REGRESSED"
                regress_speed.append(k)
            elif r < 1 - tol and (hi < 1 or (math.isnan(hi) and p < 0.05)):
                status = "improved"
                improve_speed.append(k)
            else:
                status = "same"
            qa, qb = a["iqr"], b["iqr"]
            rows.append((k, f"{fmt_val(a)} ({qa[0]:.3g}-{qa[1]:.3g})", f"{fmt_val(b)} ({qb[0]:.3g}-{qb[1]:.3g})", f"{100 * (r - 1):+.1f}%",
                         f"[{100 * (lo - 1):+.1f}%, {100 * (hi - 1):+.1f}%] p={p:.3f}", how + f"; tol {100 * tol:.0f}%", status))

    shown = [r for r in rows if args.all or r[6] not in ("same",)]
    head = ("metric", "A", "B", "delta", "95% CI", "how", "status")
    w = [max([len(head[i])] + [len(r[i]) for r in shown]) for i in range(7)]
    print("  ".join(h.ljust(w[i]) for i, h in enumerate(head)))
    print("-" * (sum(w) + 12))
    for r in shown:
        colour = RED + BOLD if r[6] == "REGRESSED" else GREEN if r[6] == "improved" else DIM if r[6] in ("same", "n/a") else ""
        print(colour + "  ".join(c.ljust(w[i]) for i, c in enumerate(r)) + END)
    if not args.all:
        print(f"{DIM}({len(rows) - len(shown)} metrics unchanged within their CI; --all lists them){END}")

    tradeoff = regress_speed and not regress_acc and improve_acc
    if regress_acc or (regress_speed and not (tradeoff and args.accept_tradeoff)):
        verdict = "regressed"
    elif improve_acc or improve_speed:
        verdict = "improved"
    else:
        verdict = "no change"
    print()
    if regress_acc:
        print(f"{RED}{BOLD}accuracy regressions{END}: {', '.join(regress_acc)}")
    if regress_speed:
        print(f"{RED}{BOLD}speed regressions (> {100 * SPEED_TOLERANCE:.0f}%){END}: {', '.join(regress_speed)}")
        if tradeoff and not args.accept_tradeoff:
            print(f"{YELLOW}accuracy improved too ({', '.join(improve_acc)}): a speed regression is acceptable only when the gain is explicit; "
                  f"state it and rerun with --accept-tradeoff{END}")
    if improve_acc or improve_speed:
        print(f"{GREEN}improvements{END}: {', '.join(improve_acc + improve_speed)}")
    colour = RED if verdict == "regressed" else GREEN if verdict == "improved" else ""
    print(f"\n{BOLD}verdict: {colour}{verdict}{END}" + (f"  {YELLOW}(with warnings above){END}" if warnings else ""))
    sys.exit(1 if verdict == "regressed" else 0)


if __name__ == "__main__":
    main()
