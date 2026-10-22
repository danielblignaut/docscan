"""OCR synthetic proof-of-address pages with docscan's own pipeline and label
every OCR word from the generator's ground truth, for train_tagger.py.

The OCR, the page preparation and the tagger's input features all come from
the Rust crate (`docscan/examples/poa.rs --words`), so training sees exactly
the words, noise and features the browser will produce. This script only
matches the OCR words to the ground-truth word boxes the generator recorded
(testdata/poa_synth.py `spans`).

  python build_dataset.py --flat  /tmp/docscan-poa/synth  --out /tmp/docscan-poa/ds/clean.jsonl
  python build_dataset.py --camera /tmp/docscan-poa/camera --out /tmp/docscan-poa/ds/camera.jsonl

Each output line: {id, layout, kind, source, ok, labels, ids, num, words, ...}.
Pages whose outline was not found (or found wrongly) are kept with ok=false
so the eval can count them as capture failures; training skips them.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POA = Path(os.environ.get("DOCSCAN_POA", ROOT / "docscan" / "target" / "release" / "examples" / "poa"))
ENTITIES = ["HOLDER_NAME", "STREET", "SUBURB", "CITY", "PROVINCE", "POSTAL_CODE", "DOC_DATE", "PERIOD_FROM", "PERIOD_TO", "ISSUER", "ACCOUNT_NO"]


def norm(s: str) -> str:
    return "".join(c for c in s.upper() if c.isalnum())


def lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def sim(a: str, b: str) -> float:
    n = max(len(a), len(b))
    return 1.0 if n == 0 else 1 - lev(a, b) / n


def run_poa(paths: list[str], flat: bool, jobs: int, extra: list[str]) -> list[dict]:
    """Runs the native pipeline over `paths` in `jobs` single-threaded processes."""
    chunks = [paths[i::jobs] for i in range(jobs)]
    env = {**os.environ, "RAYON_NUM_THREADS": "1"}

    def one(chunk: list[str]) -> list[dict]:
        if not chunk:
            return []
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("\n".join(chunk))
        args = [str(POA), "--words", *extra, *(["--flat"] if flat else []), f"@{f.name}"]
        res = subprocess.run(args, capture_output=True, text=True, env=env)
        os.unlink(f.name)
        if res.returncode:
            sys.stderr.write(res.stderr)
        return [json.loads(line) for line in res.stdout.splitlines() if line.strip()]

    out: list[dict] = []
    with ThreadPoolExecutor(jobs) as ex:
        for part in ex.map(one, chunks):
            out.extend(part)
    return out


def corner_error(found, truth, frame) -> float:
    """Largest corner distance, as a fraction of the frame diagonal."""
    diag = (frame[0] ** 2 + frame[1] ** 2) ** 0.5
    return max(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(found, truth)) / diag


def label_words(words: list[dict], page_size, truth: dict) -> list[int]:
    """BIO class per OCR word (0 = O, 1 + 2e = B-e, 2 + 2e = I-e).

    A word takes the label of the ground-truth word boxes it overlaps (at
    least 40% of its own area), when its text resembles theirs; it is B when
    the first of them begins its span."""
    W, H = truth["size"]
    sx, sy = page_size[0] / W, page_size[1] / H
    gt = []  # (box in page coords, entity index, index in span, text)
    for span in truth["spans"]:
        e = ENTITIES.index(span["label"])
        for k, w in enumerate(span["words"]):
            x0, y0, x1, y1 = w["box"]
            gt.append(((x0 * sx, y0 * sy, x1 * sx, y1 * sy), e, k, w["text"]))
    labels = []
    prev_key = None
    for w in words:
        ox0, oy0, ox1, oy1 = w["x"], w["y"], w["x"] + w["w"], w["y"] + w["h"]
        area = max(1.0, (ox1 - ox0) * (oy1 - oy0))
        hits = []
        for (x0, y0, x1, y1), e, k, text in gt:
            # A little slack: OCR boxes and font boxes differ by a few pixels.
            pad = 0.25 * (y1 - y0)
            ix = min(ox1, x1 + pad) - max(ox0, x0 - pad)
            iy = min(oy1, y1 + pad) - max(oy0, y0 - pad)
            if ix > 0 and iy > 0 and ix * iy / area >= 0.4:
                hits.append((x0, e, k, text, id(text), (x0, y0)))
        if not hits:
            labels.append(0)
            prev_key = None
            continue
        hits.sort()
        # One entity per word: the most common among its hits.
        e = max({h[1] for h in hits}, key=lambda ent: sum(h[1] == ent for h in hits))
        same = [h for h in hits if h[1] == e]
        if sim(norm(w["text"]), norm("".join(h[3] for h in same))) < 0.5:
            labels.append(0)
            prev_key = None
            continue
        # A ground-truth word the OCR split in two: the second half continues it.
        key = (e, same[0][5])
        begins = same[0][2] == 0 and key != prev_key
        prev_key = (e, same[-1][5])
        labels.append(1 + 2 * e if begins else 2 + 2 * e)
    return labels


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--flat", help="directory of clean <id>.png + <id>.json")
    g.add_argument("--camera", help="directory of <id>_cam<k>.jpg + .json (from poa_augment.py)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--save-flat", help="also write each flattened colour page (1024 px) here, for the VLM eval")
    ap.add_argument("--select", help="a file of document ids, one per line: only these")
    args = ap.parse_args()

    if args.flat:
        truths = sorted(Path(args.flat).glob("poa_*.json"))
        items = [(str(t.with_suffix(".png")), t, None) for t in truths if not t.stem.endswith("_boxes")]
    else:
        metas = sorted(Path(args.camera).glob("*_cam*.json"))
        items = []
        for m in metas:
            meta = json.loads(m.read_text())
            items.append((meta["image"], Path(meta["source"]), meta))
    if args.select:
        keep = set(Path(args.select).read_text().split())
        items = [i for i in items if Path(i[1]).stem in keep]
    if args.limit:
        items = items[: args.limit]
    results = {r["path"]: r for r in run_poa([i[0] for i in items], bool(args.flat), args.jobs, [f"--save-flat={args.save_flat}"] if args.save_flat else [])}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    n_ok = n_lab = 0
    with open(args.out, "w") as f:
        for path, truth_path, meta in items:
            truth = json.loads(Path(truth_path).read_text())
            r = results.get(path, {"error": "missing"})
            rec = {"id": truth["id"], "layout": truth["layout"], "kind": "clean" if args.flat else "camera", "source": path}
            ok = "error" not in r
            if ok and meta is not None:
                err = corner_error(r["corners"], meta["corners_tl_tr_br_bl"], meta["frame"])
                rec["corner_error"] = round(err, 4)
                ok = err < 0.05
            rec["ok"] = ok
            if "error" in r:
                rec["error"] = r["error"]
            if "words" in r:
                rec["labels"] = label_words(r["words"], r["page_size"], truth) if ok else [0] * len(r["words"])
                for k in ("words", "ids", "num", "page_size", "ms", "text", "rules", "page", "flat_image"):
                    if k in r:
                        rec[k] = r[k]
                n_lab += sum(1 for x in rec["labels"] if x)
            n_ok += ok
            f.write(json.dumps(rec) + "\n")
    print(f"{len(items)} pages, {n_ok} usable, {n_lab} labelled words -> {args.out}")


if __name__ == "__main__":
    main()
