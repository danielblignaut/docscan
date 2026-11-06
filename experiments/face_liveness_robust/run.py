"""Liveness under production conditions, on the synthetic DEV clips.

Connect replays a face check on its server from the frames the phone uploaded:
one every 100 ms (10 fps), each a JPEG of at most 640 pixels, with the
server's own configuration (nine of twelve segments, a blink required, the
identity threshold of SFace int8). The bench's liveness suite runs the clips at
their own 30 fps with every frame analysed, which never misses a blink or a
segment between frames. This runs every DEV clip through `examples/face
liveness` under named conditions and scores each:

  python run.py run   --cond server       # 10 fps, JPEG 85, Connect's server config
  python run.py run   --cond server_dim   # the same in a dim room (luma x 0.35 + noise)
  python run.py score --cond server [--cond server_dim ...]

Scores: BPCER overall and by skin tone (the clip generator's nine tones in
three bands), APCER per attack species, why each bona fide failed, blink
recall (bona fide clips the generator made blink), blinks counted on flat
attacks (which cannot blink), and the anti-spoofing decision score's margins.
Tune on DEV only; FACE_SPLIT=test is for the final report (bench/README.md).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "face/synth"))
# DEV for tuning. FACE_SPLIT=test runs the TEST clips once, to report a final
# change (bench/README.md: log it in bench/results/TEST_ACCESS.log).
SPLIT = os.environ.get("FACE_SPLIT", "dev")
CLIPS = Path(os.environ.get("BENCH_DATA", "/tmp/docscan-bench")) / "face/clips" / SPLIT
OUT = Path(os.environ.get("FACE_RUNS", Path.home() / "work/face-runs"))
BIN = Path(os.environ.get("FACE_BIN", ROOT / "docscan/target/release/examples/face"))
MODELS = ROOT / "models/face"
# The clips frame the face for this guide (face/eval/liveness.py RUN_CONFIG).
GUIDE = {"guide": [0.5, 0.5, 0.38]}
# Connect's server replay (native/docscan-verifier): coverage 0.75, blink
# required, SFace int8's identity threshold.
SERVER = {"coverage": 0.75, "require_blink": True, "min_identity": 0.366}
CONDITIONS = {
    "native30": {"config": {}, "flags": []},
    "server": {"config": SERVER, "flags": ["--every", "3", "--jpeg", "85"]},
    "server_dim": {"config": SERVER, "flags": ["--every", "3", "--jpeg", "85", "--gain", "0.55"]},
    # The phone's own engine, a frame every ~250 ms (4 fps), no blink asked.
    "browser": {"config": {"coverage": 0.75, "min_identity": 0.366}, "flags": ["--every", "7", "--jpeg", "92"]},
}


def truth(kind: str, seed: int) -> dict:
    """The skin tone and the number of blinks the generator rendered."""
    from head import SKIN_TONES, Camera, Identity  # noqa: PLC0415
    import clips  # noqa: PLC0415

    ident = Identity.random(seed)
    tone = SKIN_TONES.index(ident.skin)
    blinks: list[int] = []
    if kind == "bona_fide":
        # Replays bona_fide()'s draws up to its blink schedule.
        rng = np.random.default_rng(seed)
        Camera(480, 640, fov_deg=rng.uniform(58, 68))
        rng.uniform(34, 44), rng.uniform(-6, 4), rng.uniform(-1.0, 1.5)
        path = clips.sweep_path(rng)
        blinks = sorted(int(x) for x in rng.choice(len(path), size=2, replace=False)) if rng.random() < 0.6 else []
    return {"tone": tone, "band": ("dark", "medium", "light")[tone // 3], "blink_frames": blinks}


def every(cond: str) -> int:
    f = CONDITIONS[cond]["flags"]
    return int(f[f.index("--every") + 1]) if "--every" in f else 1


def run(cond: str, jobs: int, only: str | None):
    spec = CONDITIONS[cond]
    config = json.dumps({**GUIDE, **spec["config"]})
    out = OUT / SPLIT / cond if SPLIT != "dev" else OUT / cond
    out.mkdir(parents=True, exist_ok=True)
    clips_ = sorted(CLIPS.glob("*.y4m"))
    if only:
        clips_ = [c for c in clips_ if c.stem.startswith(only)]

    def one(clip: Path):
        cmd = [str(BIN), "--models", str(MODELS), "--recogniser", "sface_int8.onnx:sface_int8:sface", "liveness", str(clip), config, *spec["flags"]]
        r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "RAYON_NUM_THREADS": "1"})
        if r.returncode != 0:
            raise RuntimeError(f"{clip.name}: {r.stderr[-400:]}")
        (out / f"{clip.stem}.json").write_text(r.stdout)
        return clip.stem

    with ThreadPoolExecutor(jobs) as ex:
        for i, name in enumerate(ex.map(one, clips_), 1):
            print(f"{cond} {i}/{len(clips_)} {name}", flush=True)


def check(result: dict, name: str) -> dict:
    return next((c for c in result["checks"] if c["name"] == name), {})


def score(cond: str) -> dict:
    rows = []
    for f in sorted((OUT / SPLIT / cond if SPLIT != "dev" else OUT / cond).glob("*.json")):
        d = json.loads(f.read_text())
        kind, seed = f.stem.rsplit("_", 1)
        r = d["result"]
        t = truth(kind, int(seed))
        # Blinks the session saw frames of: those before it finished.
        last = (r["frames"] - 1) * every(cond)
        t["blinks"] = sum(b <= last for b in t.pop("blink_frames"))
        rows.append({"clip": f.stem, "kind": kind, **t, "passed": r["passed"], "completed": r["completed"],
                     "failed": [c["name"] for c in r["checks"] if c["required"] and not c["passed"]] + ([] if r["completed"] else ["not_completed"]),
                     "blink": check(r, "blink").get("score", 0), "antispoof": check(r, "antispoof").get("score"),
                     "samples": d["antispoof"]})
    bona = [x for x in rows if x["kind"] == "bona_fide"]
    rep = {"condition": cond, "clips": len(rows)}
    rep["bpcer"] = f"{sum(not x['passed'] for x in bona)}/{len(bona)}"
    rep["bpcer_by_band"] = {b: f"{sum(not x['passed'] for x in bona if x['band'] == b)}/{sum(x['band'] == b for x in bona)}" for b in ("dark", "medium", "light")}
    rep["bona_fide_failures"] = dict(Counter(n for x in bona for n in x["failed"]))
    blinking = [x for x in bona if x["blinks"]]
    # The clips cannot answer "Blink your eyes": those that never blink cannot pass a
    # session that requires one, so BPCER over the clips that do blink is reported too.
    rep["bpcer_blinking"] = f"{sum(not x['passed'] for x in blinking)}/{len(blinking)}"
    rep["blink_recall"] = f"{sum(x['blink'] > 0 for x in blinking)}/{len(blinking)}"
    rep["blink_recall_by_band"] = {b: f"{sum(x['blink'] > 0 for x in blinking if x['band'] == b)}/{sum(x['band'] == b for x in blinking)}" for b in ("dark", "medium", "light")}
    rep["blinks_on_clips_without"] = f"{sum(x['blink'] > 0 for x in bona if not x['blinks'])}/{sum(not x['blinks'] for x in bona)}"
    flat = [x for x in rows if x["kind"] in ("photo", "curved_photo", "video_2d")]
    rep["blinks_on_flat_attacks"] = f"{sum(x['blink'] > 0 for x in flat)}/{len(flat)}"
    rep["apcer"] = {k: f"{sum(x['passed'] for x in rows if x['kind'] == k)}/{sum(x['kind'] == k for x in rows)}"
                    for k in sorted({x["kind"] for x in rows} - {"bona_fide"})}
    done = [x for x in bona if x["completed"] and x["antispoof"] is not None]
    if done:
        rep["bona_fide_antispoof_min"] = round(min(x["antispoof"] for x in done), 3)
    att = [x for x in rows if x["kind"] != "bona_fide" and x["antispoof"] is not None and x["samples"]]
    if att:
        rep["attack_antispoof_max"] = round(max(x["antispoof"] for x in att), 3)
    return rep, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["run", "score"])
    ap.add_argument("--cond", action="append", required=True)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--only")
    ap.add_argument("--json", help="write the score reports here")
    a = ap.parse_args()
    reports = []
    for c in a.cond:
        if a.what == "run":
            run(c, a.jobs, a.only)
        else:
            rep, _ = score(c)
            reports.append(rep)
            print(json.dumps(rep, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(reports, indent=1) + "\n")


if __name__ == "__main__":
    main()
