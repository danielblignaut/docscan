"""Score proof-of-address extraction against the synthetic ground truth.

  # The rules and the trained tagger, on pages train/build_dataset.py OCR'd:
  python eval/poa_eval.py extractors --tagger models/poa-tagger.onnx /tmp/docscan-poa/ds/test_held_camera.jsonl ...
  # Items for the VLM benchmark (eval/poa_vlm.mjs): flattened pages and raw frames
  python eval/poa_eval.py items /tmp/docscan-poa/ds/test_held_camera.jsonl --n 40 --out /tmp/docscan-poa/eval
  # A VLM's answers (with the hallucination guard run on the page's OCR text):
  python eval/poa_eval.py vlm /tmp/docscan-poa/eval/vlm-*.jsonl --pages /tmp/docscan-poa/ds/test_held_camera.jsonl

A field is correct when it equals the truth after upper-casing and dropping
everything but letters and digits (dates compare as ISO dates; a field the
page does not print, such as a missing suburb, is correct only when empty).
The province is always scored against the true province: an extractor may
infer it from the postal code when the page does not print it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "docscan" / "target" / "release" / "examples"
FIELDS = ["holder_name", "street", "suburb", "city", "province", "postal_code", "document_date", "issuer", "account_number"]
KEY = ["holder_name", "street", "city", "postal_code", "document_date"]


def norm(s) -> str:
    return "".join(c for c in str(s or "").upper() if c.isalnum())


MONTHS = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def iso(s) -> str | None:
    """A date in any of the usual written forms, as ISO (VLMs ignore the asked format)."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y.%m.%d"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    m = re.match(r"(\d{1,2})\s*([A-Za-z]{3})[a-z]*\.?\s*(\d{4})", s)
    if m and m.group(2).upper() in MONTHS:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(2).upper()], int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


def flatten(f: dict | None) -> dict:
    f = f or {}
    a = f.get("address") or {}
    return {
        "holder_name": f.get("holder_name"), "street": a.get("street"), "suburb": a.get("suburb"), "city": a.get("city"),
        "province": a.get("province"), "postal_code": a.get("postal_code"), "document_date": iso(f.get("document_date")),
        "issuer": f.get("issuer"), "account_number": f.get("account_number"),
    }


def correct(field: str, pred, truth) -> bool:
    if field == "document_date":
        return (pred or None) == (truth or None)
    return norm(pred) == norm(truth)


def truth_of(source_id: str, synth: Path) -> dict:
    return json.loads((synth / f"{source_id}.json").read_text())


class Tally:
    def __init__(self):
        self.n = 0
        self.ok = defaultdict(int)
        self.key_all = 0
        self.flags = defaultdict(int)  # wrong values flagged / wrong values / right values flagged / right values

    def add(self, pred: dict, truth: dict, checks: list[dict] | None = None):
        self.n += 1
        t = flatten(truth["fields"])
        right = {f: correct(f, pred.get(f), t[f]) for f in FIELDS}
        for f, r in right.items():
            self.ok[f] += r
        self.key_all += all(right[f] for f in KEY)
        if checks is not None:
            found = {c["field"]: c["found"] for c in checks}
            for f in FIELDS:
                if pred.get(f) and f in found:
                    if right[f]:
                        self.flags["right"] += 1
                        self.flags["right_flagged"] += not found[f]
                    else:
                        self.flags["wrong"] += 1
                        self.flags["wrong_flagged"] += not found[f]

    def row(self) -> dict:
        r = {f: self.ok[f] / max(1, self.n) for f in FIELDS}
        r["key_fields_all"] = self.key_all / max(1, self.n)
        return r


def table(rows: list[tuple[str, int, dict]]) -> str:
    cols = FIELDS + ["key_fields_all"]
    head = "| Set / method | n | " + " | ".join(cols) + " |\n|" + "---|" * (len(cols) + 2) + "\n"
    return head + "".join(f"| {name} | {n} | " + " | ".join(f"{100 * r[c]:.0f}%" for c in cols) + " |\n" for name, n, r in rows)


def cmd_extractors(args):
    rows, summary = [], {}
    for path in args.pages:
        lines = Path(path).read_text().splitlines()
        if args.ids:
            keep = set(Path(args.ids).read_text().split())
            lines = [x for x in lines if json.loads(x)["id"] in keep]
        cmd = [str(BIN / "poa_fields"), *( [f"--tagger={args.tagger}"] if args.tagger else [])]
        res = subprocess.run(cmd, input="\n".join(lines), capture_output=True, text=True)
        if res.returncode:
            sys.exit(res.stderr)
        outs = [json.loads(x) for x in res.stdout.splitlines()]
        name = Path(path).stem
        tallies = {"rules": Tally(), "tagger": Tally()}
        captured = sum(1 for o in outs if o.get("ok"))  # outline within 5% of the true corners
        ms = defaultdict(list)
        for o in outs:
            truth = truth_of(o["id"], Path(args.synth))
            for m in tallies:
                if m == "tagger" and not args.tagger:
                    continue
                # Every page the pipeline read counts, whether or not its outline
                # was the right one; a page with no outline found misses every field.
                if m in o:
                    tallies[m].add(flatten(o[m]["fields"]), truth, o[m]["verification"]["fields"])
                    ms[m].append(o[m]["ms"])
                else:
                    # Not captured (no outline, or the wrong one): every field missed.
                    tallies[m].add({}, truth)
        for m, t in tallies.items():
            if t.n and (m != "tagger" or args.tagger):
                rows.append((f"{name} · {m}", t.n, t.row()))
                summary[f"{name}/{m}"] = {"n": t.n, "captured": captured, **t.row(), "flags": dict(t.flags),
                                          "extract_ms_median": sorted(ms[m])[len(ms[m]) // 2] if ms[m] else None}
    print(table(rows))
    for k, v in summary.items():
        f = v["flags"]
        print(f"{k}: captured {v['captured']}/{v['n']}; guard flags {f.get('wrong_flagged', 0)}/{f.get('wrong', 0)} wrong values, "
              f"{f.get('right_flagged', 0)}/{f.get('right', 0)} right values; extract {v['extract_ms_median']} ms")
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2))


def cmd_items(args):
    recs = [json.loads(x) for x in Path(args.pages).read_text().splitlines()]
    recs = [r for r in recs if r.get("ok") and r.get("flat_image")][: args.n]
    flat = [{"id": r["id"], "image": r["flat_image"], "truth": str(Path(args.synth) / f"{r['id']}.json")} for r in recs]
    raw = [{"id": r["id"], "image": r["source"], "truth": str(Path(args.synth) / f"{r['id']}.json")} for r in recs]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "items_flat.json").write_text(json.dumps(flat, indent=1))
    (out / "items_raw.json").write_text(json.dumps(raw, indent=1))
    (out / "items_ids.txt").write_text("\n".join(r["id"] for r in recs))
    print(f"{len(recs)} items -> {out}/items_flat.json, items_raw.json")


def cmd_vlm(args):
    pages = {}
    for p in args.pages:
        for x in Path(p).read_text().splitlines():
            r = json.loads(x)
            pages[r["id"]] = r
    rows = []
    for path in args.results:
        recs = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
        # The hallucination guard: the app's own checks, on the page's OCR text.
        inp = "\n".join(json.dumps({"text": pages.get(r["id"], {}).get("text", ""), "fields": r.get("fields") or {}}) for r in recs)
        res = subprocess.run([str(BIN / "poa_verify")], input=inp, capture_output=True, text=True)
        if res.returncode:
            sys.exit(res.stderr)
        checks = [json.loads(x) for x in res.stdout.splitlines()]
        t = Tally()
        for r, c in zip(recs, checks):
            f = r.get("fields") or {}
            pred = flatten(f)
            # As the app does, a province name is matched to the canonical one.
            t.add(pred, truth_of(r["id"], Path(args.synth)), c["fields"])
        ms = sorted(r["ms"] for r in recs)
        name = Path(path).stem
        rows.append((name, t.n, t.row()))
        fl = t.flags
        print(f"{name}: {len(recs)} pages, median {ms[len(ms) // 2] / 1000:.1f} s/page, peak RSS {max(r.get('rss_peak_mb') or 0 for r in recs)} MB, "
              f"invalid JSON {sum(1 for r in recs if r.get('fields') is None)}; guard flags {fl.get('wrong_flagged', 0)}/{fl.get('wrong', 0)} wrong values, "
              f"{fl.get('right_flagged', 0)}/{fl.get('right', 0)} right values")
    print(table(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synth", default="/tmp/docscan-poa/synth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extractors")
    e.add_argument("pages", nargs="+")
    e.add_argument("--tagger")
    e.add_argument("--json")
    e.add_argument("--ids", help="only these document ids (one per line), e.g. the VLM items")
    i = sub.add_parser("items")
    i.add_argument("pages")
    i.add_argument("--n", type=int, default=40)
    i.add_argument("--out", required=True)
    v = sub.add_parser("vlm")
    v.add_argument("results", nargs="+")
    v.add_argument("--pages", nargs="+", required=True)
    args = ap.parse_args()
    {"extractors": cmd_extractors, "items": cmd_items, "vlm": cmd_vlm}[args.cmd](args)


if __name__ == "__main__":
    main()
