"""Barcodes: per-symbology recall, precision and false decodes, all codes in a
frame, labelled-field accuracy (label and value), and native ms per frame.

Sets: `barcode_synth_dev` / `_test` (bench/data/gen_barcodes.py: exact ground
truth for every code) and `barcode_public_dev` / `_test` (real photos from a
public, licensed set; bench/data/import_barcodes_public.py). Every frame goes
through `examples/scan --barcodes` (barcode::read_all, what the wasm's
`barcodes()` runs: every symbology at once), and the labelled frames through
`examples/scan --labelled` (Scanner::labelled: barcodes, OCR and pairing).

A decode matches a truth code when the symbology and the text are identical
(UPC-A and the EAN-13 with a leading 0 are the same code). Scoring:
- recall: truth codes decoded, over the codes meant to be decodable (codes
  drawn deliberately undecodable, e.g. bars under a pixel, are excluded, and
  scored only through the labelled metrics' printed values); per symbology too;
- false_decode_frames: frames with any decode that matches no truth code
  (lower is better; negatives included). `precision` (matching decodes over
  all decodes) is reported too, but its items change with the decoder, so
  compare.py can only judge it unpaired;
- all_codes: frames whose every decodable code was read;
- labelled.value / labelled.label_value: printed fields whose value (and
  normalised label) the labelled reading lists; labelled.unread: the fields
  whose bars cannot be decoded, read from print.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lib.common import (MANIFESTS, Cache, binary, binary_key, env1, log, m_info, m_latency, m_rate, manifest, manifest_root, run_jsonl_sharded,
                        sha256_file, taskset, timed_runs)

from .id import MODELS

SYMBOLOGIES = ["qrcode", "datamatrix", "pdf417", "aztec", "code128", "code39", "code93", "codabar", "ean13", "ean8", "upca", "upce", "itf"]


def norm(s) -> str:
    return "".join(c for c in str(s or "").upper() if c.isalnum())


def canon(fmt: str, text: str) -> tuple[str, str]:
    """UPC-A is EAN-13 with a leading zero."""
    if fmt == "upca" and len(text) == 12:
        return "ean13", "0" + text
    return fmt, text


def frames_of(set_name: str, quick: bool) -> tuple[Path, list[dict]]:
    root = manifest_root(manifest(set_name))
    rows = [json.loads(l) for l in (root / "truth.jsonl").read_text().splitlines() if l.strip()]
    if quick:
        rows = rows[::5]
    for r in rows:
        r["path"] = str(root / r["image"])
    return root, rows


def run_scan(rows: list[dict], ctx, mode: str) -> dict[str, dict]:
    flag = {"barcodes": "--barcodes", "labelled": "--labelled"}[mode]
    cache = Cache(f"barcode_{mode}", binary_key("scan", models=MODELS))
    shas = {r["path"]: sha256_file(Path(r["path"])) for r in rows}
    todo = sorted({r["path"] for r in rows if cache.get(shas[r["path"]]) is None})
    if todo:
        log(f"  barcode: {mode} on {len(todo)} frames ({len(rows) - len(todo)} cached)")
        for out in run_jsonl_sharded([str(binary("scan")), flag], todo, ctx.jobs, env1(SCAN_MAX_WIDTH="100000"), list_arg=None):
            cache.put(shas[out["path"]], {k: out.get(k) for k in ("barcodes", "fields", "ms")})
        cache.save()
    return {r["path"]: cache.get(shas[r["path"]]) for r in rows}


def score(tag: str, rows: list[dict], res: dict[str, dict]) -> dict:
    p = f"barcode.{tag}"
    rec_ids, rec_ok = [], []
    per = {s: ([], []) for s in SYMBOLOGIES}
    fd_ids, fd_ok, neg_ids, neg_ok = [], [], [], []
    all_ids, all_ok = [], []
    dec_ids, dec_ok = [], []
    by_tag: dict = {}
    for r in rows:
        got = {canon(b["format"], b["text"]) for b in (res[r["path"]]["barcodes"] or [])}
        truth = {canon(c["format"], c["text"]) for c in r["codes"]}
        decodable = [c for c in r["codes"] if c.get("decodable", True)]
        for k, c in enumerate(decodable):
            hit = canon(c["format"], c["text"]) in got
            iid = f"{r['id']}:{k}"
            rec_ids.append(iid)
            rec_ok.append(hit)
            if c["format"] in per:
                per[c["format"]][0].append(iid)
                per[c["format"]][1].append(hit)
            for t in set(r.get("tags", [])) | set(c.get("tags", [])):
                bt = by_tag.setdefault(t, [0, 0])
                bt[0] += 1
                bt[1] += hit
        false = [g for g in got if g not in truth]
        fd_ids.append(r["id"])
        fd_ok.append(bool(false))
        if r.get("negative"):
            neg_ids.append(r["id"])
            neg_ok.append(bool(got))
        if decodable:
            all_ids.append(r["id"])
            all_ok.append(all(canon(c["format"], c["text"]) in got for c in decodable))
        for g in sorted(got):
            dec_ids.append(f"{r['id']}:{g[0]}:{norm(g[1])[:24]}")
            dec_ok.append(g in truth)
    out = {
        f"{p}.recall": m_rate(rec_ids, rec_ok, desc="decodable truth codes read (symbology and text exact)"),
        f"{p}.all_codes": m_rate(all_ids, all_ok, desc="frames whose every decodable code was read"),
        f"{p}.false_decode_frames": m_rate(fd_ids, fd_ok, desc="frames with a decode matching no truth code", better="lower"),
        f"{p}.precision": m_rate(dec_ids, dec_ok, desc="decodes that match a truth code (items vary with the decoder: judged unpaired)"),
    }
    if neg_ids:
        out[f"{p}.negatives_with_decode"] = m_rate(neg_ids, neg_ok, desc="frames with no barcode in which something was decoded", better="lower")
    for s in SYMBOLOGIES:
        if per[s][0]:
            out[f"{p}.recall.{s}"] = m_rate(*per[s], desc=f"{s}: decodable truth codes read")
    out[f"{p}.recall_by_condition"] = m_info({t: round(v[1] / v[0], 4) for t, v in sorted(by_tag.items())}, desc="recall per condition tag (frame and code tags)")
    return out


def score_labelled(tag: str, rows: list[dict], res: dict[str, dict]) -> dict:
    p = f"barcode.{tag}.labelled"
    v_ids, v_ok, lv_ok, u_ids, u_ok = [], [], [], [], []
    for r in rows:
        fields = res[r["path"]]["fields"] or []
        for k, f in enumerate(r["fields"]):
            want_v, want_l = norm(f["value"]), (f.get("label") or None)
            vals = [g for g in fields if norm(g.get("value")) == want_v]
            iid = f"{r['id']}:{k}"
            v_ids.append(iid)
            v_ok.append(bool(vals))
            lv_ok.append(any((g.get("label") or None) == want_l for g in vals))
            if f.get("barcode_format") and not f.get("barcode_decodable", True):
                u_ids.append(iid)
                u_ok.append(bool(vals))
    out = {f"{p}.value": m_rate(v_ids, v_ok, desc="printed fields whose value the labelled reading lists"),
           f"{p}.label_value": m_rate(v_ids, lv_ok, desc="printed fields listed with the right value and the right normalised label (or none)")}
    if u_ids:
        out[f"{p}.unread"] = m_rate(u_ids, u_ok, desc="fields whose bars cannot be decoded: value read from print")
    return out


def speed(ctx, rows: list[dict], labelled_rows: list[dict]) -> dict:
    sel = [r["path"] for r in rows if not r.get("negative")][:: max(1, len(rows) // (6 if ctx.quick else 20))][: 6 if ctx.quick else 20]
    lab = [r["path"] for r in labelled_rows][: 2 if ctx.quick else 5]
    out = {}
    for name, paths, flag, desc in (("frame_ms", sel, "--barcodes", "barcodes in a frame (read_all: every symbology, skew retry, linear rescue)"),
                                    ("labelled_ms", lab, "--labelled", "a labelled reading (barcodes, OCR in tiles, pairing)")):
        if not paths:
            continue

        def once(cpu, paths=paths, flag=flag):
            r = subprocess.run(taskset(cpu) + [str(binary("scan")), flag, *paths], capture_output=True, text=True, env=env1(SCAN_MAX_WIDTH="100000"), check=True)
            return {Path(json.loads(l)["path"]).stem: json.loads(l)["ms"] for l in r.stdout.splitlines() if l.strip()}

        t = timed_runs(once, min(ctx.repeats, 3) if flag == "--labelled" else ctx.repeats)
        out[f"barcode.speed.{name}"] = m_latency(t, desc=f"native, 1 thread, median of {t['repeats']} runs: {desc}")
    return out


def run(ctx) -> dict:
    metrics = {}
    speed_rows, speed_lab = None, None
    for split in ctx.splits:
        for kind in ("synth", "public"):
            name = f"barcode_{kind}_{split}"
            if not (MANIFESTS / f"{name}.json").exists():
                metrics[f"barcode.{kind}_{split}.missing"] = m_info(True, desc=f"{name} has no manifest: not measured")
                continue
            _, rows = frames_of(name, ctx.quick)
            res = run_scan(rows, ctx, "barcodes")
            metrics.update(score(f"{kind}_{split}", rows, res))
            lab = [r for r in rows if r.get("fields")]
            if lab:
                metrics.update(score_labelled(f"{kind}_{split}", lab, run_scan(lab, ctx, "labelled")))
            if kind == "synth" and split == "dev":
                speed_rows, speed_lab = rows, lab
    if speed_rows is None and (MANIFESTS / "barcode_synth_dev.json").exists():
        _, speed_rows = frames_of("barcode_synth_dev", True)
        speed_lab = [r for r in speed_rows if r.get("fields")]
    if speed_rows:
        metrics.update(speed(ctx, speed_rows, speed_lab or []))
    return metrics
