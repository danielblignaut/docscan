"""Simulate the browser's guide crop on each camera-like test image, run the
native scanner, and score every field against the synthetic ground truth."""
import json, subprocess, sys, os, glob
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = "/tmp/docscan-eval"
os.makedirs(OUT, exist_ok=True)
pattern = sys.argv[1] if len(sys.argv) > 1 else "*"

def crop(meta_path):
    meta = json.load(open(meta_path))
    img = Image.open(os.path.join(ROOT, "testdata", meta["image"])).convert("RGB")
    xs = [p[0] for p in meta["corners_tl_tr_br_bl"]]; ys = [p[1] for p in meta["corners_tl_tr_br_bl"]]
    mx = (max(xs) - min(xs)) * 0.06; my = (max(ys) - min(ys)) * 0.06
    box = (max(0, min(xs) - mx), max(0, min(ys) - my), min(img.width, max(xs) + mx), min(img.height, max(ys) + my))
    box = tuple(int(v) for v in box)
    c = img.crop(box)
    scale = 1.0
    if c.width > 1280: scale = 1280 / c.width; c = c.resize((1280, round(c.height * scale)), Image.BILINEAR)
    meta["_crop"] = (box[0], box[1], scale)
    out = os.path.join(OUT, os.path.basename(meta["image"]).replace(".jpg", ".png"))
    c.save(out)
    return out, meta

metas = sorted(glob.glob(os.path.join(ROOT, "testdata/camera", f"{pattern}.json")))
paths, infos = [], []
for m in metas:
    p, meta = crop(m); paths.append(p); infos.append(meta)
res = subprocess.run([os.path.join(ROOT, "docscan/target/release/examples/scan"), *paths], capture_output=True, text=True, env={**os.environ, "SCAN_MAX_WIDTH": "1280"})
if res.returncode: print(res.stderr); sys.exit(1)
results = [json.loads(l) for l in res.stdout.splitlines()]

def norm(s): return "".join(ch for ch in str(s or "").upper() if ch.isalnum())
def yymmdd(iso): return iso[2:4] + iso[5:7] + iso[8:10]

def score(kind, truth, r):
    """(field, want, got) triples for the fields a document kind should yield."""
    f = truth["fields"]; out = []
    if kind in ("za_passport", "gb_passport"):
        m = r.get("mrz") or {}
        out += [("surname", f["surname"], m.get("surname")), ("given_names", f["given_names"], m.get("given_names")),
                ("document_number", f["document_number"], m.get("document_number")),
                ("date_of_birth", yymmdd(f["date_of_birth"]), m.get("date_of_birth")),
                ("date_of_expiry", yymmdd(f["date_of_expiry"]), m.get("date_of_expiry"))]
    elif kind == "za_smart_id_back":
        b = r.get("smart_id_barcode") or {}
        out += [("id_number", f["identity_number"], (b.get("id_number") or {}).get("value"))]
    elif kind == "za_smart_id_front":
        p = r.get("printed") or {}
        for k in ("surname", "names", "sex", "nationality", "date_of_birth_printed", "country_of_birth", "status"):
            out.append((k, f[k], p.get(k.replace("_printed", ""))))
        out.append(("id_number", f["identity_number"], (p.get("id_number") or {}).get("value")))
    elif kind == "za_green_id_book":
        p = r.get("printed") or {}
        out += [("surname", f["surname"], p.get("surname")), ("names", f["forenames"], p.get("names")),
                ("id_number", f["identity_number"], (p.get("id_number") or {}).get("value"))]
    return out

KIND = {"za_green_id_book": "za_green_book"}
rows = []; totals = {}
for meta, r in zip(infos, results):
    src = json.load(open(os.path.join(ROOT, "testdata", meta["source"])))
    kind = src["kind"]; name = os.path.basename(meta["image"])
    if kind == "multi_barcode":
        want = {(b["format"].lower(), b["text"]) for b in src["barcodes"]}
        got = {(b["format"], b["text"]) for b in r["barcodes"]}
        rows.append(f"{name:34} barcodes {len(got & {(w[0], w[1]) for w in want})}/{len(want)} (ID formats only)")
        continue
    fields = score(kind, src, r)
    ok = sum(norm(w) == norm(g) for _, w, g in fields)
    bad = [(k, w, g) for k, w, g in fields if norm(w) != norm(g)]
    kind_ok = r["kind"] == KIND.get(kind, kind)
    ox, oy, sc = meta["_crop"]
    gt = [((x - ox) * sc, (y - oy) * sc) for x, y in meta["corners_tl_tr_br_bl"]]
    if r.get("document"):
        det = r["document"]["corners"]
        err = max(((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5 for a, b in zip(gt, det))
        corner = f"quad±{err:.0f}px"
    else:
        corner = "quad=none"
    t = totals.setdefault((kind, meta["expect"]), [0, 0, 0, 0]); t[0] += 1; t[1] += kind_ok and r["accepted"]; t[2] += ok; t[3] += len(fields)
    rows.append(f"{name:34} {r['kind']:18} acc={str(r['accepted']):5} fields {ok}/{len(fields)} {r['timings_ms']['total']:.0f}ms {corner} sharp={r['quality']['sharpness']:.0f} glare={r['quality']['glare']:.3f} {bad if bad else ''}")
print("\n".join(rows)); print()
for (k, e), (n, acc, ok, total) in sorted(totals.items()):
    print(f"{k:20} {e:5} accepted {acc}/{n}  fields {ok}/{total}")
