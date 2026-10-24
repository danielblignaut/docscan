"""WASM timings of the user's photo (DEV only): raw `barcodes`, full
`labelled` and the candidate `labelled_near_bars`, from the private candidate
package (/tmp/docscan-barcode-latency-v1/pkg-cand: the HEAD snapshot plus
`lib-integration.patch`; `labelled` and `barcodes` are unchanged code).

Cold: a fresh Node process per call (instantiate and model load reported
apart); warm: later calls in the same process. One CPU. Writes aggregates
only (counts, kinds, sources, ms) to the private experiment directory.

    /tmp/docscan-bench/venv/bin/python -I experiments/barcode_latency/run_wasm.py
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import CPU, EXP, MODELS, USER_IMAGE, VARIANTS, compare  # noqa: E402

PKG = EXP / "pkg-cand"
HERE = Path(__file__).resolve().parent
NODE = os.environ.get("NODE", "node")


def main() -> None:
    from PIL import Image

    if not USER_IMAGE.is_file():
        raise SystemExit("set USER_IMAGE to the private photo")
    img = Image.open(USER_IMAGE).convert("RGBA")
    w, h = img.size
    raw = EXP / "private" / "user.rgba"
    raw.write_bytes(img.tobytes())
    out: dict = {"image": "user photo (private)", "cpu": CPU, "decoder": "PIL (browser decodes with createImageBitmap)", "size": [w, h]}
    fields = {}
    # The frozen candidate (empty margins: label_regions::MARGINS) and the
    # exploratory tight preview.
    arms = {"barcodes": ("barcodes", ""), "labelled": ("labelled", ""), "near_bars_frozen": ("labelled_near_bars", ""),
            "near_bars_exploratory_tight": ("labelled_near_bars", VARIANTS["tight"])}
    for arm, (call, margins) in arms.items():
        runs = []
        for _ in range(3):
            r = subprocess.run(["taskset", "-c", CPU, NODE, str(HERE / "wasm_probe.mjs"), str(PKG), str(MODELS), str(raw), str(w), str(h), call, "4", margins],
                               capture_output=True, text=True, timeout=1800)
            if r.returncode != 0:
                raise RuntimeError(f"wasm probe failed ({r.returncode}, {len(r.stderr)} bytes of stderr)")
            runs.append(json.loads(r.stdout))
        fields[arm] = runs[0]["fields"]
        out[arm] = {"instantiate_ms_median": round(statistics.median(x["instantiateMs"] for x in runs), 1),
                     "models_ms_median": round(statistics.median(x["modelsMs"] for x in runs), 1),
                     "cold_call_ms": [round(x["ms"][0], 1) for x in runs],
                     "warm_call_ms_median": round(statistics.median(m for x in runs for m in x["ms"][1:]), 1),
                     "items": len(runs[0]["fields"])}
        if call != "barcodes":
            shown = [f for f in runs[0]["fields"] if f["check"] is not False]
            out[arm]["kinds_shown"] = {k: sum(1 for f in shown if f["kind"] == k) for k in sorted({f["kind"] for f in shown})}
            out[arm]["sources_shown"] = {k: sum(1 for f in shown if f["source"] == k) for k in sorted({f["source"] for f in shown})}
    out["frozen_vs_full"] = compare(fields["labelled"], fields["near_bars_frozen"])
    out["exploratory_tight_vs_full"] = compare(fields["labelled"], fields["near_bars_exploratory_tight"])
    raw.unlink()
    (EXP / "wasm.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
