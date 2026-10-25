"""Pre-freeze diagnosis of the Fast reader's DEV misses (DEV only).

    diag.py d0

Runs snapshot d0's diagnosis probe on the 72 labelled `barcode_synth_dev`
frames (2 workers x 1 thread) and classifies every truth field the Fast
reading does not list with its label and value: right value under a wrong
label; value printed in an OCR line exactly (a parse/association miss); or
the nearest OCR line substring 1, 2, >=3 edits away, with where the edits
fall (first/last character or interior) and their type. Writes aggregates
only (counts by class, label, edit position) to d0/runs/diag-<time>.json;
values and line texts stay in memory.

This ran BEFORE the candidates were chosen and frozen; it informs the
choice and is reported as such. It does not look at any single frame.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(os.environ.get("LABEL_ROBUSTNESS_DIR", "/tmp/docscan-label-robustness"))
DATA = Path(os.environ.get("BENCH_DATA", "/tmp/docscan-bench")) / "barcode" / "synth_dev"
CPUS = os.environ.get("LABEL_ROBUSTNESS_CPUS", "6,7").split(",")


def norm(s) -> str:
    return "".join(c for c in str(s or "").upper() if c.isalnum())


def shown(fields):
    return [f for f in fields if f.get("check_digit_valid") is not False]


def substring_edits(pat: str, text: str) -> tuple[int, list[tuple[str, int]]]:
    """Semi-global alignment of pat inside text: (distance, [(op, pattern index)])."""
    n, m = len(pat), len(text)
    if n == 0:
        return 0, []
    INF = 10 ** 9
    d = [[0] * (m + 1)] + [[i] + [INF] * m for i in range(1, n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j - 1] + (pat[i - 1] != text[j - 1]), d[i - 1][j] + 1, d[i][j - 1] + 1)
    j = min(range(m + 1), key=lambda j: d[n][j])
    dist, ops, i = d[n][j], [], n
    while i > 0:
        if j > 0 and d[i][j] == d[i - 1][j - 1] + (pat[i - 1] != text[j - 1]):
            if pat[i - 1] != text[j - 1]:
                ops.append(("sub", i - 1))
            i, j = i - 1, j - 1
        elif d[i][j] == d[i - 1][j] + 1:
            ops.append(("del", i - 1))  # a pattern character missing from the text
            i -= 1
        else:
            ops.append(("ins", i))  # an extra text character before pattern index i
            j -= 1
    return dist, ops


def where(op_i: int, n: int) -> str:
    return "first" if op_i <= 0 else "last" if op_i >= n - 1 else "interior"


def run(paths: list[str], cpu: str, probe: Path, models: Path) -> list[dict]:
    env = {**os.environ, "RAYON_NUM_THREADS": "1", "RTEN_NUM_THREADS": "1"}
    r = subprocess.run(["taskset", "-c", cpu, str(probe), f"--models={models}"] + paths, capture_output=True, text=True, env=env, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"probe failed ({r.returncode}, {len(r.stderr)} bytes of stderr)")
    return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]


def bump(d: dict, *keys) -> None:
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = d.get(keys[-1], 0) + 1


def main() -> None:
    snap = ROOT / sys.argv[1]
    rows = [json.loads(l) for l in (DATA / "truth.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("fields")]
    for r in rows:
        r["path"] = str(DATA / r["image"])
    paths = [r["path"] for r in rows]
    chunks = [paths[i::len(CPUS)] for i in range(len(CPUS))]
    with ThreadPoolExecutor(len(CPUS)) as ex:
        outs = list(ex.map(lambda ic: run(ic[1], CPUS[ic[0]], snap / "target-bin", snap / "models"), enumerate(chunks)))
    res = {o["path"]: o for out in outs for o in out}
    agg: dict = {"frames": len(rows), "truth_fields": 0, "label_value_hits": 0, "false_fields": 0, "misses": {}, "false": {}}
    for r in rows:
        o = res[r["path"]]
        fs = shown(o["fields"])
        texts = [norm(l["text"]) for l in o["lines"]]
        truth_v = {norm(f["value"]) for f in r["fields"]} | {norm(c["text"]) for c in r["codes"]}
        for f in r["fields"]:
            agg["truth_fields"] += 1
            v, lab = norm(f["value"]), f.get("label") or "unlabelled"
            if any(norm(g.get("value")) == v and (g.get("label") or None) == (f.get("label") or None) for g in fs):
                agg["label_value_hits"] += 1
                continue
            bar = "no_barcode" if f["barcode_format"] is None else ("bars_decodable" if f["barcode_decodable"] else "bars_undecodable")
            if any(norm(g.get("value")) == v for g in fs):
                bump(agg["misses"], "wrong_label", lab)
                continue
            best = min((substring_edits(v, t) for t in texts), key=lambda x: x[0], default=(len(v), []))
            dist, ops = best
            cls = "exact_in_line" if dist == 0 else f"d{dist}" if dist <= 2 else "d3plus_or_absent"
            bump(agg["misses"], "by_class", cls, lab)
            bump(agg["misses"], "by_barcode", cls, bar)
            if 0 < dist <= 2:
                size = "x".join(map(str, r["size"]))
                bump(agg["misses"], "slip_by_size", size)
                bump(agg["misses"], "slip_by_difficulty", r["difficulty"])
                bump(agg["misses"], "slip_em_px", str(int(r["params"].get("text_em_px", 0) // 2 * 2)))
                for op, i in ops:
                    bump(agg["misses"], "edit_position", where(i, len(v)))
                    bump(agg["misses"], "edit_type", op)
                    if op == "sub":
                        bump(agg["misses"], "sub_class", "digit" if v[i].isdigit() else "letter")
        for g in fs:
            gv = norm(g.get("value"))
            if gv in truth_v:
                continue
            agg["false_fields"] += 1
            near = min((substring_edits(gv, t)[0] for t in truth_v), default=99)
            dd = min(near, min((substring_edits(t, gv)[0] for t in truth_v), default=99))
            bump(agg["false"], "by_kind_label", f"{g['kind']}:{g.get('label') or 'unlabelled'}")
            bump(agg["false"], "nearest_truth_edits", str(dd) if dd <= 2 else "3plus")
    agg["frames_by_size"] = {}
    for r in rows:
        bump(agg, "frames_by_size", "x".join(map(str, r["size"])))
    agg["lines_total"] = sum(len(o["lines"]) for o in res.values())
    agg["probe"] = "d0 diag.rs (unpatched HEAD)"
    (snap / "runs").mkdir(exist_ok=True)
    p = snap / "runs" / f"diag-{time.strftime('%Y%m%dT%H%M%S')}.json"
    with open(p, "x") as fh:
        fh.write(json.dumps(agg, indent=1, sort_keys=True) + "\n")
    print(json.dumps(agg, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
