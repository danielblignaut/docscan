"""The real-world barcode set: zxing-cpp's test/samples (Apache-2.0), with
ground truth from its own expected-result files.

  python bench/data/import_barcodes_public.py --split dev|test

Fetches github.com/zxing-cpp/zxing-cpp at a pinned commit (a sparse, blobless
clone of test/samples: GitHub's tarballs omit that folder), reads every
sample's truth the way zxing-cpp's own test runner does (a port of
readTestConfig in test/blackbox/BlackboxTestRunner.cpp: per-folder
`!defaults.toml`, per-image `.txt` or `.toml`, files shared by name prefix,
`!` suffixes for images zxing-cpp itself is expected to miss), and writes
$BENCH_DATA/barcode/public_<split>/images/<folder>/<file> and truth.jsonl in
the synthetic set's format.

Kept: the 13 symbologies docscan reads. Skipped: binary truth (TextHex),
Code 39 variants whose text is not raw Code 39 (Code 32, PZN), synthetic
merged structured-append results, and folders of other symbologies. Text is
stored in ZXing's (and rxing's) convention where zxing-cpp's differs: UPC-A as
12 digits, UPC-E as 8, EAN add-ons dropped (docscan does not read them);
Code 39 extended keeps its full-ASCII text (rxing reads it only in extended
mode, so those three are expected misses). Codes zxing-cpp itself is expected
to miss carry the tag `reference_fails`.

The split keeps every photo of one barcode on one side: DEV when the first
byte of sha256(first code's text) is even (negatives: of the file name), TEST
otherwise. Mixed content: real phone photos and scans, and some clean
computer-generated symbols.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

DATA = Path(os.environ.get("BENCH_DATA", "/tmp/docscan-bench"))
REPO = "https://github.com/zxing-cpp/zxing-cpp"
COMMIT = "2c3dcfeffa7878950a58c1703c86774a428b0c91"
CLONE = DATA / "raw" / "barcodes" / "_src" / "zxing-cpp"
SRC = str(CLONE / "test" / "samples")
LICENCE = ("Apache-2.0: zxing-cpp's test/samples (github.com/zxing-cpp/zxing-cpp @ " + COMMIT[:12] + ", LICENSE and "
           "BlackboxTestRunner.cpp SPDX-License-Identifier: Apache-2.0). Fetched to /tmp for evaluation, never committed.")

IMG_EXT = {'.webp', '.png', '.jpg', '.jpeg', '.pgm', '.gif'}

# zxing-cpp BarcodeFormat name -> benchmark format
FMT = {'QR Code': 'qrcode', 'Data Matrix': 'datamatrix', 'PDF417': 'pdf417', 'Aztec': 'aztec',
       'Code 128': 'code128', 'Code 39': 'code39', 'Code 93': 'code93', 'Codabar': 'codabar',
       'EAN-13': 'ean13', 'EAN-8': 'ean8', 'UPC-A': 'upca', 'UPC-E': 'upce', 'ITF': 'itf'}
# directory stem (before first '-') -> zxing-cpp format name
DIRFMT = {'qrcode': 'QR Code', 'datamatrix': 'Data Matrix', 'pdf417': 'PDF417', 'aztec': 'Aztec',
          'code128': 'Code 128', 'code39': 'Code 39', 'code39ext': 'Code 39', 'code93': 'Code 93',
          'codabar': 'Codabar', 'ean13': 'EAN-13', 'ean8': 'EAN-8', 'upca': 'UPC-A', 'upce': 'UPC-E',
          'itf': 'ITF', 'multi': 'None', 'none': 'None'}
LINEAR = {'Code 128', 'Code 39', 'Code 93', 'Codabar', 'EAN-13', 'EAN-8', 'UPC-A', 'UPC-E', 'ITF'}
CTRL = ['NUL','SOH','STX','ETX','EOT','ENQ','ACK','BEL','BS','HT','LF','VT','FF','CR','SO','SI','DLE',
        'DC1','DC2','DC3','DC4','NAK','SYN','ETB','CAN','EM','SUB','ESC','FS','GS','RS','US']
UNESC = {n: chr(i) for i, n in enumerate(CTRL)}; UNESC['DEL'] = '\x7f'

def unescape_nongraphical(s):
    def r(m):
        k = m.group(1)
        if k in UNESC: return UNESC[k]
        if k.startswith('U+'): return chr(int(k[2:], 16))
        raise ValueError(k)
    return re.sub(r'<([A-Z]{2,3}|U\+[0-9A-F]{4,6})>', r, s)

def parse_toml_value(v):
    v = v.strip()
    if len(v) < 2 or v[0] != '"' or v[-1] != '"': return v
    out, i = [], 1
    while i < len(v) - 1:
        c = v[i]
        if c != '\\': out.append(c); i += 1; continue
        n = v[i + 1]
        if n in 'uU':
            k = 4 if n == 'u' else 8
            out.append(chr(int(v[i + 2:i + 2 + k], 16))); i += 2 + k; continue
        out.append({'"': '"', '\\': '\\', 'b': '\b', 't': '\t', 'n': '\n', 'f': '\f', 'r': '\r'}[n]); i += 2
    return ''.join(out)

def read_toml(path, folder_defaults):
    if not os.path.exists(path): return [dict(folder_defaults)]
    records, defaults = [], dict(folder_defaults); current = dict(defaults); top = True
    for raw in open(path, encoding='utf-8').read().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'): continue
        if line == '[[symbol]]':
            if top: top = False; defaults = dict(current)
            else: records.append(current); current = dict(defaults)
            continue
        k, _, v = line.partition('=')
        current[k.strip()] = parse_toml_value(v)
    records.append(current)
    return records

def parse_filter(value):
    res, mode = set(), None
    for c in value:
        if c == ' ': continue
        if c in 'sfp': mode = c; continue
        rots = {'0': [0], '1': [1], '2': [2], '3': [3], 'h': [0, 2], 'v': [1, 3], 'a': [0, 1, 2, 3]}[c]
        res |= {(mode, r) for r in rots}
    return res

def read_test_config(img, defaults):
    base, _ = os.path.splitext(img)
    data = base
    while not os.path.exists(data + '.toml') and not os.path.exists(data + '.txt'):
        d, stem = os.path.split(data)
        sep = max(stem.rfind(ch) for ch in '-_!')
        if sep < 0: break
        data = os.path.join(d, stem[:sep])
    if os.path.exists(data + '.toml'): data_path = data + '.toml'; ret = read_toml(data_path, defaults)
    elif os.path.exists(data + '.txt'):
        data_path = data + '.txt'; ret = [dict(defaults)]
        b = open(data_path, 'rb').read()
        try: ret[0]['_txt'] = b.decode('utf-8')
        except UnicodeDecodeError: ret[0]['_txt_binary'] = b.hex()
    else: data_path = None; ret = [dict(defaults)]
    stem = os.path.basename(base)
    if stem.endswith('!') or data_path is None: ret[0]['missing'] = 'sa fa pa'
    elif stem.endswith('!f'): ret[0]['missing'] = 'fa pa'
    elif stem.endswith('!p'): ret[0]['missing'] = 'pa'
    return ret, data_path

def upca_to_upce(a12):
    """Compress a 12-digit UPC-A to 8-digit UPC-E if possible (inverse of ZXing convertUPCEtoUPCA)."""
    ns, m, p, ck = a12[0], a12[1:6], a12[6:11], a12[11]
    if ns not in '01': return None
    cands = []
    if m[2] in '012' and m[3:] == '00' and p[:2] == '00': cands.append(m[:2] + p[2:] + m[2])
    if m[3:] == '00' and p[:3] == '000': cands.append(m[:3] + p[3:] + '3')
    if m[4] == '0' and p[:4] == '0000': cands.append(m[:4] + p[4] + '4')
    if m[4] != '0' and p[:4] == '0000' and p[4] in '56789': cands.append(m + p[4])
    for c in cands:
        e = ns + c + ck
        if expand_upce(e) == a12: return e
    return None

def expand_upce(e8):
    d, last = e8[1:7], e8[6]
    if last in '012': mid = d[0:2] + last + '0000' + d[2:5]
    elif last == '3': mid = d[0:3] + '00000' + d[3:5]
    elif last == '4': mid = d[0:4] + '00000' + d[4]
    else: mid = d[0:5] + '0000' + last
    return e8[0] + mid + e8[7]



def fetch():
    if (CLONE / "test" / "samples").is_dir() and subprocess.run(["git", "-C", str(CLONE), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() == COMMIT:
        return
    if CLONE.exists():
        shutil.rmtree(CLONE)
    CLONE.parent.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", "-C", str(CLONE), *a], check=True)  # noqa: E731
    subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout", "--sparse", REPO, str(CLONE)], check=True)
    run("sparse-checkout", "set", "test/samples", "test/blackbox")
    run("checkout", COMMIT)


def entries():
    """Every usable sample: {image, codes: [{format, text, ...}], source_dir, negative?} (zxing-cpp's truth)."""
    out = []
    for dname in sorted(os.listdir(SRC)):
        dpath = os.path.join(SRC, dname)
        if not os.path.isdir(dpath):
            continue
        stem = dname.split("-")[0]
        dirfmt = DIRFMT.get(stem)
        if dirfmt is None:
            continue
        imgs = sorted(f for f in os.listdir(dpath) if os.path.splitext(f)[1].lower() in IMG_EXT)
        defaults = {"find": "sh fh" if dirfmt in LINEAR else "sa fh", "Format": dirfmt}
        defaults = read_toml(os.path.join(dpath, "!defaults.toml"), defaults)[0]
        for f in imgs:
            recs, data_path = read_test_config(os.path.join(dpath, f), defaults)
            codes, reason = [], None
            for r in recs:
                fmt = r.get("Format")
                if fmt == "None" and stem == "none":
                    continue
                if r.get("SequenceIndex") == "-1":
                    continue
                if fmt not in FMT:
                    reason = "format"
                    break
                if "_txt_binary" in r or "TextHex" in r:
                    reason = "binary"
                    break
                if "_txt" in r:
                    text = r["_txt"]
                elif "TextPlain" in r:
                    text = r["TextPlain"]
                elif "TextEscaped" in r:
                    text = unescape_nongraphical(r["TextEscaped"])
                else:
                    reason = "no text"
                    break
                expect = parse_filter(r["find"])
                if "missing" in r:
                    expect -= parse_filter(r["missing"])
                n = FMT[fmt]
                main, addon = text, ""
                if n in ("ean13", "upca", "upce") and len(text) in (15, 18):
                    main, addon = text[:13], text[13:]
                alt = None
                if n == "upca" and main.startswith("0") and len(main) == 13:
                    alt = main[1:]
                if n == "upce" and main.startswith("0") and len(main) == 13:
                    alt = upca_to_upce(main[1:])
                if n == "ean13" and addon:
                    alt = main
                codes.append({"format": n, "text": alt or main, "reference_fails": not bool({e for e in expect if e[0] != "p"})})
            if reason or (stem == "code39" and f.startswith(("code32", "pzn"))):
                continue
            e = {"image": f"{dname}/{f}", "codes": codes, "source_dir": dname}
            if stem == "none":
                e["negative"] = True
            out.append(e)
    return out


def split_of(e) -> str:
    key = e["codes"][0]["text"] if e["codes"] else e["image"]
    return "dev" if hashlib.sha256(key.encode()).digest()[0] % 2 == 0 else "test"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    a = ap.parse_args()
    fetch()
    out = DATA / "barcode" / f"public_{a.split}"
    if out.exists():
        shutil.rmtree(out)
    rows = []
    for e in entries():
        if split_of(e) != a.split:
            continue
        dst = out / "images" / e["image"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(os.path.join(SRC, e["image"]), dst)
        rows.append({"id": e["image"].rsplit(".", 1)[0], "image": f"images/{e['image']}", "negative": bool(e.get("negative")),
                     "tags": [e["source_dir"]], "codes": [{"format": c["format"], "text": c["text"], "decodable": True,
                                                           "tags": ["reference_fails"] if c["reference_fails"] else []} for c in e["codes"]]})
    (out / "truth.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in sorted(rows, key=lambda r: r["id"])))
    (out / "source.json").write_text(json.dumps({"source": f"{REPO} @ {COMMIT}: test/samples", "licence": LICENCE,
        "description": f"Real-world barcodes ({a.split.upper()} half): zxing-cpp's test samples, phone photos, scans and some clean "
                       "symbols of 13 symbologies, with zxing-cpp's own expected results as truth (bench/data/import_barcodes_public.py)."}, indent=1))
    c = collections.Counter(code["format"] for r in rows for code in r["codes"])
    print(f"public {a.split}: {len(rows)} images ({sum(r['negative'] for r in rows)} negative), codes {dict(c)}")


if __name__ == "__main__":
    main()
