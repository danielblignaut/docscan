import json, subprocess, sys, os
from PIL import Image, ImageDraw
paths = sys.argv[1:]
res = subprocess.run(["docscan/target/release/examples/scan", *paths], capture_output=True, text=True)
for p, line in zip(paths, res.stdout.splitlines()):
    r = json.loads(line); im = Image.open(p).convert("RGB"); d = ImageDraw.Draw(im)
    if r.get("document"):
        c = [tuple(x) for x in r["document"]["corners"]]; d.line(c + [c[0]], fill=(255, 0, 0), width=5)
    out = "/tmp/draw_" + os.path.basename(p); im.save(out); print(out, r["kind"], r.get("document"))
