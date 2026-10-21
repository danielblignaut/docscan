"""The benchmark driver (bench/run.sh calls it after building and preparing).

  python bench/bench.py [--suite all|id,barcode,poa,face] [--split dev|test|both] [--quick]
                        [--repeats N] [--no-cache] [--no-wasm] [--e2e] [--out FILE]

Writes bench/results/<git-sha>-<UTC timestamp>.json and prints a table.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import common  # noqa: E402
from lib.common import BENCH, BIN, MANIFESTS, ROOT, bench_code_sha256, loadavg, log, safe_digest, sha256_file  # noqa: E402

SUITES = ["id", "barcode", "poa", "face"]
SETS_OF = {
    "id": {"dev": ["id_stills", "id_clips", "id_hard_dev"], "test": ["id_hard_test"]},
    "barcode": {"dev": ["barcode_synth_dev", "barcode_public_dev"], "test": ["barcode_synth_test", "barcode_public_test"]},
    "poa": {"dev": ["poa_dev"], "test": ["poa_lockbox"]},
    "face": {"dev": ["face_lfw", "face_docpairs_dev", "face_celeba_dev", "face_liveness_dev"],
             "test": ["face_lfw", "face_docpairs_test", "face_celeba_test", "face_liveness_test"]},
}


@dataclass
class Ctx:
    splits: list[str]
    quick: bool
    jobs: int
    repeats: int
    skip_clips: bool = False
    notes: list[str] = field(default_factory=list)


def git(*a) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def tool_version(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip().splitlines()[0]
    except Exception:
        return None


def meta(args, sets: list[str]) -> dict:
    dirty = [l for l in git("status", "--porcelain").splitlines() if "bench/results/" not in l]
    cpu = next((l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines() if l.startswith("model name")), platform.processor())
    bins = {b: safe_digest(sha256_file(BIN / b)) for b in ("scan", "poa", "poa_capture", "face") if (BIN / b).exists()}
    models = {str(p.relative_to(ROOT)): safe_digest(sha256_file(p)) for p in sorted((ROOT / "models").rglob("*")) if p.is_file() and p.suffix in {".rten", ".onnx"}}
    mans = {}
    for s in sets:
        p = MANIFESTS / f"{s}.json"
        if p.exists():
            m = json.loads(p.read_text())
            mans[s] = {"tree_sha256": m["tree_sha256"], "count": m["count"], "split": m["split"]}
    return {
        "git_sha": git("rev-parse", "HEAD"), "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"), "git_dirty": dirty,
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "args": {k: v for k, v in vars(args).items()}, "host": platform.node(), "cpu": cpu, "logical_cpus": os.cpu_count(),
        "load_start": loadavg(), "jobs": args.jobs, "python": platform.python_version(), "rustc": tool_version(["rustc", "--version"]),
        "node": tool_version(["node", "--version"]), "binaries": bins, "models": models, "manifests": mans,
        "bench_code_sha256": safe_digest(bench_code_sha256()),
    }


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def fmt_value(m: dict) -> str:
    v = m.get("value")
    if m["kind"] == "info":
        return "" if isinstance(v, (dict, list)) else str(v)
    if v is None or (isinstance(v, float) and v != v):
        return "-"
    if m.get("unit") == "%":
        return f"{100 * v:.2f}%"
    if m.get("unit") in ("ms", "s"):
        return f"{v:.3g} {m['unit']}" if v < 100 else f"{v:.0f} {m['unit']}"
    return f"{v:.4g}"


def fmt_spread(m: dict) -> str:
    if m["kind"] in ("rate", "stat") and m.get("ci95") and m["ci95"][0] == m["ci95"][0]:
        lo, hi = m["ci95"]
        return f"[{100 * lo:.1f}, {100 * hi:.1f}]" if m.get("unit") == "%" else f"[{lo:.3g}, {hi:.3g}]"
    if m["kind"] == "latency":
        q1, q3 = m["iqr"]
        f = (lambda x: f"{x:.0f}") if q3 >= 100 else (lambda x: f"{x:.3g}")
        return f"IQR {f(q1)}-{f(q3)}"
    return ""


def table(metrics: dict) -> str:
    rows = [("metric", "value", "n", "95% CI / spread", "")]
    for k, m in metrics.items():
        if m["kind"] == "info" and isinstance(m.get("value"), (dict, list)):
            continue
        arrow = {"higher": "^", "lower": "v"}.get(m.get("better"), "")
        rows.append((k, fmt_value(m), str(m.get("n", "")), fmt_spread(m), arrow))
    w = [max(len(r[i]) for r in rows) for i in range(5)]
    lines = []
    for i, r in enumerate(rows):
        lines.append("  ".join(c.ljust(w[j]) if j in (0, 3) else c.rjust(w[j]) for j, c in enumerate(r)))
        if i == 0:
            lines.append("-" * len(lines[0]))
    return "\n".join(lines)


def dump(result: dict, path: Path):
    """One metric per line: reviewable diffs, compact files."""
    lines = ["{", f' "meta": {json.dumps(result["meta"], ensure_ascii=False)},', ' "metrics": {']
    items = list(result["metrics"].items())
    for i, (k, m) in enumerate(items):
        lines.append(f"  {json.dumps(k)}: {json.dumps(m, separators=(',', ':'), ensure_ascii=False)}{',' if i < len(items) - 1 else ''}")
    lines += [" }", "}"]
    path.write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# Optional browser measurements
# --------------------------------------------------------------------------- #


def wasm_inputs(ctx) -> dict:
    """A small fixed subset of every suite's DEV data (whatever is prepared)."""
    D = common.DATA
    n = 2 if ctx.quick else 5
    inp = {"repeats": ctx.repeats, "barcodes": [], "document": [], "page": [], "face": []}
    inp["barcodes"] = [str(p) for p in sorted((D / "id/stills/camera").glob("multi_barcode_good_*.jpg"))[:n]]
    inp["document"] = [str(D / f"id/hard_dev/frames/{k}_00_base.png") for k in ("za_smart_id_front", "za_smart_id_back", "za_green_id_book", "za_passport", "gb_passport")][:n]
    inp["document"] = [p for p in inp["document"] if Path(p).exists()]
    inp["page"] = [str(p) for p in sorted((D / "poa/dev/frames").glob("*_f0.jpg"))[: 1 if ctx.quick else 3]]
    clip = D / "face/clips/dev/bona_fide_1000.y4m"
    if clip.exists():
        import numpy as np
        from PIL import Image
        out = common.CACHE / "wasm_face_frames"
        out.mkdir(parents=True, exist_ok=True)
        data = clip.read_bytes()
        header, rest = data.split(b"\n", 1)
        toks = header.split()
        w = int([t for t in toks if t.startswith(b"W")][0][1:])
        h = int([t for t in toks if t.startswith(b"H")][0][1:])
        size = w * h * 3 // 2
        fl = len(b"FRAME\n") + size
        for k in range(30, 130 if not ctx.quick else 70, 10):
            p = out / f"bona_fide_1000_{k:03d}.png"
            if not p.exists():
                import cv2
                yuv = np.frombuffer(rest[k * fl + 6 : k * fl + 6 + size], np.uint8).reshape(h * 3 // 2, w)
                Image.fromarray(cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)).save(p)
            inp["face"].append(str(p))
    return inp


def wasm(ctx) -> dict:
    out_json = common.DATA / "wasm-result.json"
    in_json = common.DATA / "wasm-inputs.json"
    in_json.write_text(json.dumps(wasm_inputs(ctx)))
    out_json.unlink(missing_ok=True)
    load0 = loadavg()
    calib = [common.calibrate(None)]
    cmd = ["node", str(BENCH / "wasm" / "bench.mjs"), "--inputs", str(in_json), "--out", str(out_json)] + (["--quick"] if ctx.quick else [])
    r = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    sys.stderr.write(r.stderr[-3000:])
    if r.returncode or not out_json.exists():
        return {"wasm.error": common.m_info(r.stderr[-500:] or "failed", desc="wasm benchmark failed")}
    calib.append(common.calibrate(None))
    data = json.loads(out_json.read_text())
    metrics = {}
    for build, rows in data["builds"].items():
        for name, row in rows.items():
            if not row["items"]:
                continue
            t = {"items": row["items"], "samples": row["samples"], "repeats": row["repeats"], "cpu": None, "load_start": load0, "load_end": loadavg(),
                 "calib_ms": round(sum(calib) / len(calib), 2), "calib_all": [round(c, 2) for c in calib]}
            m = common.m_latency(t, desc=f"headless Chrome, {build} wasm ({row['threads']} thread{'s' if row['threads'] > 1 else ''}): {row['desc']}")
            m["threads"] = row["threads"]
            metrics[f"wasm.{build}.{name}"] = m
    metrics["wasm.info"] = common.m_info(data.get("info", {}), desc="browser, builds and what was measured")
    return metrics


def e2e(ctx) -> dict:
    res = ROOT / "demo" / "e2e" / "out" / "results-bench.json"
    r = subprocess.run(["node", "e2e/run.mjs"], cwd=ROOT / "demo", text=True, capture_output=True, env={**os.environ, "E2E_TAG": "-bench"})
    sys.stderr.write(r.stdout[-1500:])
    if not res.exists():
        return {"e2e.error": common.m_info(r.stderr[-500:] or "no results", desc="demo/e2e/run.mjs failed to run")}
    rows = json.loads(res.read_text())
    out = {"e2e.pass": common.m_rate([x["name"] for x in rows], [x["ok"] for x in rows], desc="demo/e2e/run.mjs cases passing (headless Chrome, fake camera)")}
    caps = {}
    for x in rows:
        c = [round(e["sinceStartMs"] / 1000, 2) for e in x.get("captures", []) if e.get("sinceStartMs") is not None]
        caps[x["name"]] = {"ok": x["ok"], "capture_s": c, "finish_s": round(x["finishMs"] / 1000, 2) if x.get("finishMs") else None,
                           "fast_ms": (x.get("timings") or {}).get("fastMs"), "ocr_ms": (x.get("timings") or {}).get("ocrMs"), "why": x.get("why")}
    out["e2e.cases"] = common.m_info(caps, desc="per case: pass, capture times from the clip's start (s), per-frame browser timings")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--suite", default="all")
    ap.add_argument("--split", default="dev", choices=["dev", "test", "both"])
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--repeats", type=int)
    ap.add_argument("--jobs", type=int, default=common.JOBS)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-wasm", action="store_true")
    ap.add_argument("--e2e", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()
    suites = SUITES if args.suite == "all" else args.suite.split(",")
    splits = ["dev", "test"] if args.split == "both" else [args.split]
    repeats = args.repeats or (2 if args.quick else 5)
    common.Cache.enabled = not args.no_cache
    ctx = Ctx(splits=splits, quick=args.quick, jobs=args.jobs, repeats=repeats)
    sets = sorted({s for su in suites for sp in splits for s in SETS_OF[su][sp]})
    result = {"meta": meta(args, sets), "metrics": {}}
    t_all = time.time()
    for su in suites:
        log(f"== {su} ==")
        t0 = time.time()
        mod = importlib.import_module(f"suites.{su}")
        result["metrics"].update(mod.run(ctx))
        result["metrics"][f"{su}.runtime_s"] = common.m_info(round(time.time() - t0, 1), desc="wall time of the suite (s)", unit="s")
    if not args.no_wasm:
        log("== wasm ==")
        t0 = time.time()
        result["metrics"].update(wasm(ctx))
        result["metrics"]["wasm.runtime_s"] = common.m_info(round(time.time() - t0, 1), desc="wall time (s)", unit="s")
    if args.e2e:
        log("== e2e ==")
        result["metrics"].update(e2e(ctx))
    result["meta"]["load_end"] = loadavg()
    result["meta"]["runtime_s"] = round(time.time() - t_all, 1)
    common.save_hash_cache()
    sha = result["meta"]["git_sha"][:10]
    stamp = result["meta"]["timestamp_utc"].replace(":", "").replace("-", "")
    out = Path(args.out) if args.out else BENCH / "results" / f"{sha}-{stamp}{'-quick' if args.quick else ''}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    dump(result, out)
    if "test" in splits:
        with open(BENCH / "results" / "TEST_ACCESS.log", "a") as f:
            f.write(f"{result['meta']['timestamp_utc']} {sha} suites={','.join(suites)} quick={args.quick} user={os.environ.get('USER', '?')} -> {out.name}\n")
    print(table(result["metrics"]))
    print(f"\n{out}  ({result['meta']['runtime_s']} s; load {result['meta']['load_start']} -> {result['meta']['load_end']})")


if __name__ == "__main__":
    main()
