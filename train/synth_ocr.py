"""Training pages for the tagger without running OCR: every word a page drew
(testdata/poa_wide.py records them as `words_all`), put through a simple
model of ocrs's mistakes, then ordered, featurised (docscan's own
`examples/poa_feats --order`, so the features are the live pipeline's) and
labelled from the generator's spans exactly as train/build_dataset.py labels
real OCR.

OCR costs about 3 s a page on an idle core (and far more on a busy one);
this costs milliseconds, so the tagger can see many thousands of layouts,
names, streets and places. It does not replace real OCR'd pages (it knows
nothing of camera blur or the page finder): train on both.

The noise, per word: dropped (1%, 8% in print under 13 px); characters
swapped for their usual look-alikes (1.2% a character, 4% in small print),
a comma read as a full stop (25%), a full stop as a comma (5%); joined to
the next word on its line (3%) or split in two (1%); its box moved by a
pixel or two and its height by up to 10%.

  python train/synth_ocr.py --truth /tmp/docscan-poa-work/wide --out /tmp/docscan-poa-work/ds/wide_synth.jsonl [--copies 1]
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from build_dataset import label_words  # noqa: E402

CONFUSE = {
    "O": "0D", "0": "OD", "D": "O0", "I": "l1|", "l": "I1i", "1": "lI", "i": "l1", "S": "5s", "5": "S", "s": "5", "B": "8",
    "8": "B", "Z": "2", "2": "Z", "G": "6C", "6": "G", "e": "c", "c": "e", "n": "r", "u": "v", "v": "u", "a": "o", "o": "a",
    "h": "b", "b": "h", "g": "q", "q": "g", "C": "G", "E": "F", "F": "E", "M": "N", "N": "M", "U": "V", "V": "U", "t": "f",
    "f": "t", "y": "v", "m": "rn",
}


def noisy_text(t: str, rng: random.Random, small: bool) -> str:
    p = 0.04 if small else 0.012
    out = []
    for c in t:
        r = rng.random()
        if c == "," and r < 0.25:
            out.append(".")
        elif c == "." and r < 0.05:
            out.append(",")
        elif c in CONFUSE and r < p:
            out.append(rng.choice(CONFUSE[c]) if len(CONFUSE[c]) > 1 and c != "m" else CONFUSE[c])
        elif r < p + 0.002:
            continue  # a character lost
        else:
            out.append(c)
    s = "".join(out)
    return s or t


def page_words(truth: dict, rng: random.Random) -> tuple[list[dict], list[int]]:
    W, H = truth["size"]
    k = 1754 / max(W, H)
    words = []
    raw = truth["words_all"]
    i = 0
    while i < len(raw):
        w = raw[i]
        small = w.get("size", 16) < 13
        if rng.random() < (0.08 if small else 0.01):
            i += 1
            continue
        x0, y0, x1, y1 = w["box"]
        text = w["text"]
        # Joined to the next word on the same line.
        if i + 1 < len(raw) and rng.random() < 0.03:
            nx = raw[i + 1]
            if abs(nx["box"][1] - y0) < 2 and 0 <= nx["box"][0] - x1 < 0.6 * (y1 - y0):
                text += nx["text"]
                x1 = nx["box"][2]
                i += 1
        text = noisy_text(text, rng, small)
        hj = rng.uniform(0.95, 1.1)
        cy = (y0 + y1) / 2 + rng.uniform(-1, 1)
        h = (y1 - y0) * hj
        box = [x0 + rng.uniform(-1.5, 1.5), cy - h / 2, x1 + rng.uniform(-1.5, 1.5), cy + h / 2]
        if len(text) >= 6 and rng.random() < 0.01:
            cut = rng.randint(2, len(text) - 2)
            xm = box[0] + (box[2] - box[0]) * cut / len(text)
            parts = [(text[:cut], [box[0], box[1], xm - 2, box[3]]), (text[cut:], [xm + 2, box[1], box[2], box[3]])]
        else:
            parts = [(text, box)]
        for t, b in parts:
            words.append({"text": t, "x": round(b[0] * k, 1), "y": round(b[1] * k, 1), "w": round((b[2] - b[0]) * k, 1), "h": round((b[3] - b[1]) * k, 1)})
        i += 1
    return words, [round(W * k), round(H * k)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", nargs="+", required=True, help="directories of poa_wide.py output")
    ap.add_argument("--out", required=True)
    ap.add_argument("--copies", type=int, default=1, help="noisy readings per page")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--feats", default=str(ROOT.parent / "docscan" / "target" / "release" / "examples" / "poa_feats"))
    args = ap.parse_args()
    rng = random.Random(args.seed)
    truths = {}
    lines = []
    for d in args.truth:
        for p in sorted(Path(d).glob("poa_*.json")):
            t = json.loads(p.read_text())
            if not t.get("words_all"):
                continue
            truths[t["id"]] = t
            for c in range(args.copies):
                words, size = page_words(t, rng)
                lines.append(json.dumps({"id": t["id"], "layout": t["layout"], "kind": "synth", "source": str(p), "ok": True,
                                         "page_size": size, "words_raw": words, "copy": c}))
    r = subprocess.run([args.feats, "--order"], input="\n".join(lines), capture_output=True, text=True, check=True)
    n_lab = 0
    with open(args.out, "w") as f:
        for line in r.stdout.splitlines():
            rec = json.loads(line)
            rec["labels"] = label_words(rec["words"], rec["page_size"], truths[rec["id"]])
            n_lab += sum(1 for x in rec["labels"] if x)
            f.write(json.dumps(rec) + "\n")
    print(f"{len(lines)} pages, {n_lab} labelled words -> {args.out}")


if __name__ == "__main__":
    main()
