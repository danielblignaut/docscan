#!/usr/bin/env python3
"""Fetch checksum-pinned optional PP-OCRv6 tiny assets and stage same-origin copies."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads(Path(__file__).with_name('ppocr-v6-models.json').read_text())
models, public = ROOT / 'models', ROOT / 'demo/public/models'
models.mkdir(exist_ok=True)
public.mkdir(parents=True, exist_ok=True)
for item in manifest['artifacts']:
    path = ROOT / item['source'] if 'source' in item else models / item['filename']
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        if 'url' not in item:
            raise SystemExit(f"Committed PP-OCR dictionary does not match its manifest: {path}")
        with urllib.request.urlopen(item['url'], timeout=120) as source:
            data = source.read()
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise SystemExit(f"PP-OCR model checksum mismatch: {item['filename']}")
        temporary = path.with_suffix(path.suffix + '.download')
        temporary.write_bytes(data)
        temporary.replace(path)
    if path.stat().st_size != item['bytes']:
        raise SystemExit(f"PP-OCR model size mismatch: {item['filename']}")
    staged = public / (item['filename'] + '.staged')
    shutil.copyfile(path, staged)
    staged.replace(public / item['filename'])
    print(f"Verified optional PP-OCR asset: {item['filename']}")
# Include the upstream model license and attribution with distributed weights.
shutil.copyfile(ROOT / 'LICENSE-APACHE', public / 'ppocr-v6-LICENSE.txt')
shutil.copyfile(ROOT / 'scripts/ppocr-v6-NOTICE.txt', public / 'ppocr-v6-NOTICE.txt')
