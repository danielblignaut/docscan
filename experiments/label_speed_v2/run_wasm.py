"""WASM timings and fields (DEV only) from the patched snapshot's single-threaded package.

    USER_IMAGE=... USER_REPORT=... run_wasm.py SNAP user   # the user's photo, cold x3 + warm
    run_wasm.py SNAP dev                                    # 8 DEV frames, warm, fields vs native full

Cold: a fresh Node process per call (instantiate and model load reported
apart); warm: later calls in the same process. One CPU. Verifies the frozen
package hash first; writes aggregates only (counts, kinds, flags, ms) to SNAP/runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run  # noqa: E402

HERE = Path(__file__).resolve().parent
NODE = os.environ.get("NODE", "node")
CALLS = ["labelled", "labelled_once", "labelled_fast"]


def pkg_hash(pkg: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(pkg.glob("docscan*")):
        h.update(p.name.encode() + run.sha(p).encode())
    return h.hexdigest()


def call(snap: run.Snap, rgba: Path, w: int, h: int, name: str, repeat: int) -> dict:
    r = subprocess.run(["taskset", "-c", run.CPUS[0], NODE, str(HERE / "wasm_probe.mjs"), str(snap.dir / "pkg"), str(snap.models), str(rgba), str(w), str(h), name, str(repeat)],
                       capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"wasm probe failed ({r.returncode}, {len(r.stderr)} bytes of stderr)")
    return json.loads(r.stdout)


def rgba_file(path: str, tmp: Path) -> tuple[Path, int, int]:
    from PIL import Image

    img = Image.open(path).convert("RGBA")
    f = tmp / "frame.rgba"
    f.write_bytes(img.tobytes())
    return f, img.size[0], img.size[1]


def main() -> None:
    snap, phase = run.Snap(sys.argv[1]), sys.argv[2]
    f = json.loads((snap.dir / "freeze.json").read_text())
    assert pkg_hash(snap.dir / "pkg") == f["wasm_pkg"], "wasm package changed since freeze"
    for m, hsh in f["models"].items():
        assert run.sha(snap.models / m) == hsh
    prov = {"freeze": run.sha(snap.dir / "freeze.json"), "runner": {p.name: run.sha(p) for p in sorted(HERE.glob("*.py")) + sorted(HERE.glob("*.mjs"))}}
    out: dict = {"provenance": prov, "cpu": run.CPUS[0], "node": subprocess.run([NODE, "--version"], capture_output=True, text=True).stdout.strip(), "decoder": "PIL"}
    with tempfile.TemporaryDirectory(dir=snap.dir) as td:
        tmp = Path(td)
        if phase == "user":
            raw, w, h = rgba_file(str(run.USER_IMAGE), tmp)
            fields = {}
            for c in CALLS:
                runs = [call(snap, raw, w, h, c, 4) for _ in range(3)]
                fields[c] = runs[0]["fields"]
                out[c] = {"instantiate_ms_median": round(statistics.median(x["instantiateMs"] for x in runs), 1),
                          "models_ms_median": round(statistics.median(x["modelsMs"] for x in runs), 1),
                          "cold_call_ms": [round(x["ms"][0], 1) for x in runs],
                          "warm_call_ms_median": round(statistics.median(m for x in runs for m in x["ms"][1:]), 1),
                          "memory_mb": round(max(x["memoryBytes"] for x in runs) / 2**20, 1),
                          "stable": all(x["fields"] == runs[0]["fields"] for x in runs),
                          "vs_report": run.vs_report(runs[0]["fields"])}
            for c in CALLS[1:]:
                out[c]["vs_labelled"] = run.compare(fields["labelled"], fields[c])
                out[c]["warm_speedup"] = round(out["labelled"]["warm_call_ms_median"] / out[c]["warm_call_ms_median"], 2)
        else:
            rows = run.dev_rows()
            picks = []
            for size in ([720, 1280], [1280, 720], [1920, 1080], [640, 480]):
                picks += [r for r in rows if r["size"] == size][1::2][:2]
            res: dict = {c: {} for c in CALLS}
            ms: dict = {c: [] for c in CALLS}
            for r in picks:
                raw, w, h = rgba_file(r["path"], tmp)
                for c in CALLS:
                    x = call(snap, raw, w, h, c, 2)
                    res[c][r["path"]] = {"fields": x["fields"]}
                    ms[c].append(x["ms"][1])
            out["frame_ids"] = [r["id"] for r in picks]
            for c in CALLS:
                out[c] = {"warm_ms_median": round(statistics.median(ms[c]), 1), "warm_ms_sum": round(sum(ms[c]), 1), **run.truth_score(picks, res[c])}
            for c in CALLS[1:]:
                out[c]["vs_labelled"] = run.sums([run.compare(res["labelled"][p]["fields"], res[c][p]["fields"]) for p in res[c]])
                out[c]["speedup_sum"] = round(out["labelled"]["warm_ms_sum"] / out[c]["warm_ms_sum"], 2)
    snap.write(f"wasm-{phase}", out)


if __name__ == "__main__":
    main()
