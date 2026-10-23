"""Active liveness benchmark on the synthetic clips (face/synth/clips.py).

  python liveness.py run  dev|test [--jobs 8] [--config JSON]   # native sessions, one per clip
  python liveness.py score dev|test [--config JSON]             # APCER / BPCER from the saved runs

Each clip is run through `examples/face liveness` (the same Rust session the
browser runs), at the clip's 30 fps with every frame analysed. A clip is
accepted when the session completes and every required check passes.

Metrics (ISO/IEC 30107-3): APCER per attack type (presentation-attack
instrument species) = attacks accepted / attacks; BPCER = bona fide rejected /
bona fide; the worst APCER over species with the BPCER; ACER = their mean
(deprecated by the standard, but what small-model papers report).

The check thresholds can be re-applied offline to the saved scores
(`--config '{"min_parallax": 0.05}'`), so tuning never needs a rerun; tune
on DEV only, then run TEST once.
"""
import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "docscan/target/release/examples/face"
CLIPS = Path("/tmp/face-data/clips")
RUNS = Path("/tmp/face-data/liveness-runs")
DEFAULTS = {"min_parallax": 0.06, "min_antispoof": 0.711, "min_identity": 0.5}  # min_antispoof: antispoof::session_threshold()
# The clips frame the face (and attackers hold their print or screen) for a
# guide of this radius (a share of the frame's shorter side). The demo passes
# its own oval's geometry; an attacker adjusts distance until the size hint
# is satisfied, so the eval must not let a size mismatch stop an attack.
RUN_CONFIG = {"guide": [0.5, 0.5, 0.38]}
CHECK_THRESHOLD = {"3d_motion": "min_parallax", "antispoof": "min_antispoof", "identity": "min_identity"}


def run_one(clip: Path, out: Path, config: str | None):
    cfg = {**RUN_CONFIG, **(json.loads(config) if config else {})}
    cmd = [str(BIN), "--models", "/tmp/face-models", "liveness", str(clip), json.dumps(cfg)]
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "RAYON_NUM_THREADS": "1"})
    if r.returncode != 0:
        raise RuntimeError(f"{clip}: {r.stderr[-500:]}")
    out.write_text(r.stdout)
    return clip.name


def run(split: str, jobs: int, config: str | None, only: str | None):
    clips = sorted((CLIPS / split).glob("*.y4m"))
    if only:
        clips = [c for c in clips if c.name.startswith(only)]
    d = RUNS / split
    d.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(jobs) as ex:
        for name in ex.map(lambda c: run_one(c, d / (c.stem + ".json"), config), clips):
            print(name, flush=True)


def decide(result: dict, thresholds: dict):
    """Re-applies thresholds to a saved session result."""
    ok = result["completed"]
    failed = []
    for c in result["checks"]:
        if not c["required"]:
            continue
        key = CHECK_THRESHOLD.get(c["name"])
        passed = c["score"] >= thresholds[key] if key else c["passed"]
        if not passed:
            failed.append(c["name"])
    return ok and not failed, failed


def score(split: str, overrides: dict, verbose=False):
    th = {**DEFAULTS, **overrides}
    rows = []
    for f in sorted((RUNS / split).glob("*.json")):
        d = json.loads(f.read_text())
        kind = f.stem.rsplit("_", 1)[0]
        accepted, failed = decide(d["result"], th)
        checks = {c["name"]: c["score"] for c in d["result"]["checks"]}
        rows.append({"clip": f.stem, "kind": kind, "accepted": accepted, "failed": failed, "completed": d["result"]["completed"], "duration_s": d["result"]["duration_ms"] / 1000, "checks": checks, "ms": d.get("ms_median")})
    kinds = sorted({r["kind"] for r in rows})
    out = {"split": split, "thresholds": th, "per_kind": {}}
    for k in kinds:
        rs = [r for r in rows if r["kind"] == k]
        acc = sum(r["accepted"] for r in rs)
        entry = {"n": len(rs), "accepted": acc}
        if k == "bona_fide":
            entry["bpcer"] = 1 - acc / len(rs)
            done = [r["duration_s"] for r in rs if r["completed"]]
            entry["median_completion_s"] = sorted(done)[len(done) // 2] if done else None
        else:
            entry["apcer"] = acc / len(rs)
        # Which checks stopped them (the first failing one per clip).
        stops = {}
        for r in rs:
            why = "accepted" if r["accepted"] else ("not completed" if not r["completed"] else r["failed"][0])
            stops[why] = stops.get(why, 0) + 1
        entry["outcomes"] = stops
        for c in ("3d_motion", "antispoof", "identity"):
            vals = sorted(r["checks"].get(c, 0) for r in rs)
            if vals:
                entry[f"{c}_min_med_max"] = [round(vals[0], 3), round(vals[len(vals) // 2], 3), round(vals[-1], 3)]
        out["per_kind"][k] = entry
    attacks = [k for k in kinds if k != "bona_fide"]
    # "partial" is a bona fide person who did not finish: it counts as an
    # attack species here (it must not pass), not as BPCER.
    apcer_max = max((out["per_kind"][k]["apcer"] for k in attacks), default=0.0)
    bpcer = out["per_kind"].get("bona_fide", {}).get("bpcer", 0.0)
    out["apcer_max"] = apcer_max
    out["bpcer"] = bpcer
    out["acer"] = (apcer_max + bpcer) / 2
    if verbose:
        for r in rows:
            print(r["clip"], "ACCEPT" if r["accepted"] else "reject", r["failed"], {k: round(v, 3) for k, v in r["checks"].items()})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("split", choices=["dev", "test"])
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--config", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.split, a.jobs, a.config, a.only)
    print(json.dumps(score(a.split, json.loads(a.config) if a.config else {}, a.v), indent=1))
