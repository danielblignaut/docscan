"""Download only the four official pinned PP-OCRv6 ONNX snapshots, outside git."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--out', type=Path, default=Path('/tmp/docscan-ppocr-v6'))
args = p.parse_args()
provenance = json.loads(Path(__file__).with_name('models.json').read_text())
for kind, meta in provenance.items():
    folder = args.out / kind
    folder.mkdir(parents=True, exist_ok=True)
    for name, info in meta['files'].items():
        target = folder / name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == info['sha256']:
            continue
        with urllib.request.urlopen(info['url'], timeout=120) as response:
            data = response.read()
        if len(data) != info['bytes'] or hashlib.sha256(data).hexdigest() != info['sha256']:
            raise SystemExit(f'Artifact integrity mismatch: {kind}/{name}')
        temporary = target.with_suffix(target.suffix + '.download')
        temporary.write_bytes(data)
        temporary.replace(target)
    print(kind, meta['revision'])
(args.out / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
