"""Proof of address: the DEV and LOCKBOX verification metrics (genuine
accepted, rejection per negative case), blind key-field accuracy, per-field
accuracy, and native ms per frame read.

The same two stages as eval/poa_capture_eval.py, with its scoring functions
(eval/poa_eval.py: FIELDS, KEY, flatten, correct):
1. every frame through `examples/poa --words` (page analysis, outline,
   flattening, enhancement, OCR), cached by the binary's and models' bytes
   and the frame's bytes, so a change to OCR or page finding is always
   re-measured and a change elsewhere is not;
2. `examples/poa_capture` with the committed tagger: the frames the live
   pipeline picks (two, then more while they disagree, at most four), the
   voted fields, and the decision about the known customer; and every frame on
   its own.

Per capture: `genuine_accept` (a genuine case accepted), `reject_<case>` (each
negative case rejected), `key_fields` (holder name, street, city, postal code
and date all right, blind: no customer used), `field.<name>` per field. The
`single.*` metrics score every frame alone.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from lib.common import (ROOT, Cache, binary, binary_key, env1, log, m_info, m_latency, m_rate, manifest, manifest_root, run_jsonl_sharded,
                        sha256_file, taskset, timed_runs)

sys.path.insert(0, str(ROOT / "eval"))
from poa_eval import FIELDS, KEY, correct, flatten  # noqa: E402

MODELS = [ROOT / "models" / "text-detection.rten", ROOT / "models" / "text-recognition.rten"]
TAGGER = ROOT / "models" / "poa-tagger.onnx"
TODAY = "2026-10-15"
CASES = ["genuine", "wrong_person", "wrong_address", "old", "issuer_decoy"]
KEEP = ("page", "error", "fallback", "corners", "words", "page_size", "ms", "timeout", "crash")


def captures(set_name: str, quick: bool) -> tuple[Path, list[dict], dict]:
    root = manifest_root(manifest(set_name))
    caps = [json.loads(p.read_text()) for p in sorted((root / "frames").glob("*.json"))]
    if quick:
        caps = caps[::10]
    truths = {c["id"]: json.loads((root / "docs" / f"{c['id']}.json").read_text()) for c in caps}
    for c in caps:  # paths relative to this set's own frames/ (the JSON records where it was generated)
        for f in c["frames"]:
            f["path"] = str(root / "frames" / Path(f["image"]).name)
    return root, caps, truths


def ocr(caps: list[dict], ctx) -> dict[str, dict]:
    cache = Cache("poa_ocr", binary_key("poa", models=MODELS))
    paths = [f["path"] for c in caps for f in c["frames"]]
    shas = {p: sha256_file(Path(p)) for p in paths}
    todo = [p for p in paths if cache.get(shas[p]) is None]
    if todo:
        log(f"  poa: OCR of {len(todo)} frames ({len(paths) - len(todo)} cached), {ctx.jobs} processes")
        for r in run_jsonl_sharded([str(binary("poa")), "--words"], todo, ctx.jobs):
            cache.put(shas[r["path"]], {k: r.get(k) for k in KEEP})
        cache.save()
    return {p: cache.get(shas[p]) for p in paths}


def capture_run(caps: list[dict], truths: dict, pages: dict) -> dict:
    lines = []
    for c in caps:
        fr = [pages[f["path"]] for f in c["frames"]]
        lines.append(json.dumps({"id": c["id"], "customer": truths[c["id"]]["customer"], "frames": [
            {k: f.get(k) for k in ("words", "page_size", "page", "error", "fallback")} for f in fr]}))
    r = subprocess.run([str(binary("poa_capture")), f"--today={TODAY}", f"--tagger={TAGGER}"], input="\n".join(lines),
                       capture_output=True, text=True, env=env1())
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:])
    return {d["id"]: d for d in (json.loads(x) for x in r.stdout.splitlines() if x.strip())}


def score(tag: str, caps: list[dict], truths: dict, out: dict) -> dict:
    metrics = {}
    for mode in ("capture", "single"):
        ver = {c: ([], []) for c in CASES}
        key_ids, key_ok = [], []
        fld = {f: ([], []) for f in FIELDS}
        for cap in caps:
            cid = cap["id"]
            t = truths[cid]
            r = out[cid]
            results = [r["capture"]] if mode == "capture" else r["frames"]
            for k, res in enumerate(results):
                iid = cid if mode == "capture" else f"{cid}:{k}"
                accepted = bool((res.get("verify") or {}).get("accepted"))
                ver[t["case"]][0].append(iid)
                ver[t["case"]][1].append(accepted == t["expect_accept"])
                pred, truth = flatten(res.get("fields")), flatten(t["fields"])
                right = {f: correct(f, pred.get(f), truth[f]) for f in FIELDS}
                key_ids.append(iid)
                key_ok.append(all(right[f] for f in KEY))
                for f in FIELDS:
                    fld[f][0].append(iid)
                    fld[f][1].append(right[f])
        p = f"poa.{tag}" + ("" if mode == "capture" else ".single")
        unit = "capture" if mode == "capture" else "single frame"
        metrics[f"{p}.genuine_accept"] = m_rate(*ver["genuine"], desc=f"genuine cases accepted (per {unit})")
        for c in CASES[1:]:
            metrics[f"{p}.reject_{c}"] = m_rate(*ver[c], desc=f"'{c}' cases rejected (per {unit})")
        metrics[f"{p}.key_fields"] = m_rate(key_ids, key_ok, desc=f"blind: holder, street, city, postal code and date all right (per {unit})")
        if mode == "capture":
            for f in FIELDS:
                metrics[f"{p}.field.{f}"] = m_rate(*fld[f], desc=f"blind: {f} right (per capture)")
    reads = [out[c["id"]]["capture"].get("frames_read", 0) for c in caps]
    metrics[f"poa.{tag}.frames_read_mean"] = m_info(round(float(np.mean(reads)), 3), desc="frames read per capture (mean)")
    return metrics


def speed(ctx, caps: list[dict]) -> dict:
    n = 2 if ctx.quick else 6
    frames = [c["frames"][0]["path"] for c in caps[:: max(1, len(caps) // n)]][:n]
    repeats = min(ctx.repeats, 3)

    def once(cpu):
        r = subprocess.run(taskset(cpu) + [str(binary("poa")), f"--tagger={TAGGER}", *frames], capture_output=True, text=True, env=env1(), check=True)
        out = {}
        for line in r.stdout.splitlines():
            d = json.loads(line)
            if "ms" in d:
                out[Path(d["path"]).stem] = sum(float(v) for v in d["ms"].values())
        return out

    t = timed_runs(once, repeats)
    return {"poa.speed.frame_ms": m_latency(t, desc=f"native, 1 thread, median of {repeats} runs: one frame read (decode, page outline, "
                                               "flatten, enhance, OCR, rules, tagger)")}


def run(ctx) -> dict:
    metrics = {}
    dev_caps = None
    if ctx.speed_only:
        _, caps, _ = captures("poa_dev", ctx.quick)
        return speed(ctx, caps)
    sets = ([("dev", "poa_dev")] if "dev" in ctx.splits else []) + ([("lockbox", "poa_lockbox")] if "test" in ctx.splits else [])
    for tag, name in sets:
        _, caps, truths = captures(name, ctx.quick)
        pages = ocr(caps, ctx)
        out = capture_run(caps, truths, pages)
        metrics.update(score(tag, caps, truths, out))
        if tag == "dev":
            dev_caps = caps
    if dev_caps is None:
        _, dev_caps, _ = captures("poa_dev", True)
    metrics.update(speed(ctx, dev_caps))
    fm = metrics["poa.speed.frame_ms"]["value"]
    if "poa.dev.frames_read_mean" in metrics:
        metrics["poa.speed.capture_ms_est"] = m_info(round(fm * metrics["poa.dev.frames_read_mean"]["value"]), unit="ms",
                                                     desc="frame_ms x DEV frames read per capture (voting and verification add < 0.12 s)")
    return metrics
