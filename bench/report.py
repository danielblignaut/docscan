"""Run-to-run noise and the baseline summary.

  python bench/report.py noise RUN1.json RUN2.json [--out bench/noise.json]
  python bench/report.py baseline BASELINE.json [--noise bench/noise.json] [--quick QUICK.json] > bench/BASELINE.md

`noise`: the same code measured twice. For each metric the absolute
difference between the runs (rates and statistics, in their own unit: 0.01 is
one point), and for latencies |median per-item ratio - 1|. compare.py
treats a delta within a metric's noise as no change, so a noisy metric cannot
produce a verdict on its own.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import stats  # noqa: E402


def load(p):
    return json.loads(Path(p).read_text())


def noise(a: dict, b: dict) -> dict:
    out = {}
    for k, ma in a["metrics"].items():
        mb = b["metrics"].get(k)
        if not mb or ma["kind"] != mb["kind"] or ma["kind"] == "info":
            continue
        if ma["kind"] == "latency":
            ia, ib = dict(zip(ma["ids"], ma["samples"])), dict(zip(mb["ids"], mb["samples"]))
            shared = [i for i in ma["ids"] if i in ib]
            if shared:
                r, _, _ = stats.paired_latency_ratio([ia[i] for i in shared], [ib[i] for i in shared])
                if ma.get("calib_ms") and mb.get("calib_ms"):
                    r /= mb["calib_ms"] / ma["calib_ms"]
                out[k] = round(abs(r - 1), 4)
        elif ma["value"] is not None and mb["value"] is not None:
            out[k] = round(abs(mb["value"] - ma["value"]), 6)
    return out


def fmt(m: dict) -> str:
    v = m["value"]
    if v is None or (isinstance(v, float) and v != v):
        return "-"
    if m.get("unit") == "%":
        return f"{100 * v:.2f}%"
    if m.get("unit") in ("ms", "s"):
        return f"{v:.0f} {m['unit']}" if v >= 100 else f"{v:.3g} {m['unit']}"
    return f"{v:.4g}"


def spread(m: dict) -> str:
    if m["kind"] in ("rate", "stat") and m.get("ci95") and m["ci95"][0] == m["ci95"][0]:
        lo, hi = m["ci95"]
        return f"{100 * lo:.1f}-{100 * hi:.1f}%" if m.get("unit") == "%" else f"{lo:.3g}-{hi:.3g}"
    if m["kind"] == "latency":
        q1, q3 = m["iqr"]
        return f"IQR {q1:.0f}-{q3:.0f}" if q3 >= 100 else f"IQR {q1:.3g}-{q3:.3g}"
    return ""


def noise_cell(k: str, m: dict, nz: dict) -> str:
    if k not in nz:
        return ""
    v = nz[k]
    if m["kind"] == "latency":
        return f"{100 * v:.1f}%"
    if m.get("unit") == "%":
        return "0" if v == 0 else f"{100 * v:.2f} pt"
    return f"{v:.4g}"


def baseline(b: dict, nz: dict, quick: dict | None) -> str:
    m = b["meta"]
    lines = [f"# Baseline: `{m['git_sha'][:10]}`", "",
             f"Measured {m['timestamp_utc']} on {m['cpu']} ({m['logical_cpus']} logical CPUs), {m['jobs']} parallel jobs for accuracy, "
             f"speed on one pinned core; load average {m['load_start']} at the start and {m.get('load_end')} at the end "
             f"(other users' jobs share this machine). Full run: {m.get('runtime_s')} s. Splits: {m['args']['split']}.", "",
             "Value: the metric on the whole set. 95% CI: bootstrap over items (rates and statistics) or the IQR across items "
             "(latencies). Noise: the difference between two full runs of the same commit; 0 means the metric is deterministic "
             "(the same frames give the same readings), so any change at all is the code's. Latency noise is the median per-item "
             "ratio between the runs.", ""]
    suites = []
    for k in b["metrics"]:
        s = k.split(".")[0]
        if s not in suites:
            suites.append(s)
    for s in suites:
        lines += [f"## {s}", "", "| Metric | Value | n | 95% CI / spread | Noise | Better | What |", "|---|---|---|---|---|---|---|"]
        for k, mm in b["metrics"].items():
            if not k.startswith(s + ".") or mm["kind"] == "info" and isinstance(mm.get("value"), (dict, list)):
                continue
            if mm["kind"] == "info":
                lines.append(f"| `{k}` | {mm['value']}{(' ' + mm['unit']) if mm.get('unit') else ''} | | | | | {mm['desc']} |")
                continue
            lines.append(f"| `{k}` | {fmt(mm)} | {mm.get('n', '')} | {spread(mm)} | {noise_cell(k, mm, nz)} | {mm.get('better', '')} | {mm['desc']} |")
        lines.append("")
    if quick:
        lines += ["## Quick run", "", f"`--quick` on the same commit: {quick['meta'].get('runtime_s')} s (load {quick['meta']['load_start']}).", ""]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("noise")
    n.add_argument("a")
    n.add_argument("b")
    n.add_argument("--out", default=str(Path(__file__).resolve().parent / "noise.json"))
    bl = sub.add_parser("baseline")
    bl.add_argument("result")
    bl.add_argument("--noise", default=str(Path(__file__).resolve().parent / "noise.json"))
    bl.add_argument("--quick")
    a = ap.parse_args()
    if a.cmd == "noise":
        out = noise(load(a.a), load(a.b))
        Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
        print(f"{len(out)} metrics; non-zero: {sum(1 for v in out.values() if v)} -> {a.out}")
    else:
        nz = json.loads(Path(a.noise).read_text()) if Path(a.noise).exists() else {}
        sys.stdout.write(baseline(load(a.result), nz, load(a.quick) if a.quick else None))


if __name__ == "__main__":
    main()
