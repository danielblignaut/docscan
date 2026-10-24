#!/usr/bin/env python3
"""Fetch licensed public synthetic document DEV/TRAIN data; never extract TEST.

No source image or customer-like text is written to the repository. Sources
are publisher releases, not arbitrary personal bank statements found online.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import urllib.request
import zipfile
from PIL import Image

HERE = Path(__file__).resolve().parent
PROTOCOL = json.loads((HERE / 'protocol.json').read_text())
ROOT = Path(os.environ.get('DOCSCAN_PUBLIC_DATA', '/tmp/docscan-public-data'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url, target, *, md5=None, size=None):
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + '.part')
        try:
            with urllib.request.urlopen(url, timeout=120) as source, tmp.open('wb') as out:
                while chunk := source.read(1024 * 1024):
                    out.write(chunk)
            if size is not None and tmp.stat().st_size != size:
                raise ValueError('download size mismatch')
            if md5 and hashlib.md5(tmp.read_bytes()).hexdigest() != md5:
                raise ValueError('publisher archive checksum mismatch')
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
    data = target.read_bytes()
    if md5 and hashlib.md5(data).hexdigest() != md5:
        raise ValueError('publisher archive checksum mismatch')
    if size is not None and len(data) != size:
        raise ValueError('download size mismatch')
    return {'url': url, 'sha256': digest(data), 'bytes': len(data)}


def prepare_bank():
    p = PROTOCOL['bankstatemently']; dest = ROOT / 'bankstatemently'
    base = f"https://raw.githubusercontent.com/{p['repository']}/{p['revision']}/"
    names = ['LICENSE', 'README.md', 'manifest.json']
    for identity in p['dev']:
        names += [f'datasets/basic/{identity}/{identity}-statement.pdf', f'datasets/basic/{identity}/statement-info.json']
    files = []
    for name in names:
        files.append({'path': name, **fetch(base + name, dest / name)})
    released = json.loads((dest / 'manifest.json').read_text())['statements']
    for identity in p['dev']:
        path = f'datasets/basic/{identity}/{identity}-statement.pdf'
        row = next(r for r in files if r['path'] == path)
        assert row['sha256'].startswith(released[identity]['pdfChecksum'])
    result = {'protocol': p, 'files': files}
    (dest / 'pinned.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def prepare_fatura():
    p = PROTOCOL['fatura']; dest = ROOT / 'fatura'; archive = dest / 'FATURA.zip'
    src = fetch(p['url'], archive, md5=p['md5'], size=p['bytes'])
    groups = [set(p[k]) for k in ['train_templates', 'dev_templates', 'reserved_templates']]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    rows = []
    with zipfile.ZipFile(archive) as z:
        for split in ['train', 'dev']:
            for template in p[f'{split}_templates']:
                for instance in p[f'{split}_instances']:
                    identity = f'Template{template}_Instance{instance}'
                    image_member = f'invoices_dataset_final/images/{identity}.jpg'
                    annotation_member = f'invoices_dataset_final/Annotations/Original_Format/{identity}.json'
                    image_bytes, annotation_bytes = z.read(image_member), z.read(annotation_member)
                    image = Image.open(io.BytesIO(image_bytes)); width, height = image.size
                    fields = []
                    for label, value in json.loads(annotation_bytes).items():
                        # OTHER is upstream OCR, not ground truth. TABLE has
                        # geometry but no exact text labels: neither is truth.
                        if label in {'OTHER', 'TABLE', 'LOGO'} or not isinstance(value, dict): continue
                        if not isinstance(value.get('text'), str) or not value.get('bbox'): continue
                        points = value['bbox']
                        xs, ys = [v[0] for v in points], [v[1] for v in points]
                        box = [min(xs), height - max(ys), max(xs), height - min(ys)]
                        fields.append({'label': label, 'text': value['text'], 'bbox': box})
                    folder = dest / split; folder.mkdir(exist_ok=True)
                    (folder / f'{identity}.jpg').write_bytes(image_bytes)
                    record = {'id': identity, 'template': template, 'split': split, 'width': width, 'height': height, 'image_sha256': digest(image_bytes), 'annotation_sha256': digest(annotation_bytes), 'fields': fields}
                    (folder / f'{identity}.json').write_text(json.dumps(record, ensure_ascii=False) + '\n')
                    rows.append({k: v for k, v in record.items() if k != 'fields'})
    result = {'protocol': p, 'archive': src, 'documents': rows}
    (dest / 'pinned.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    os.umask(0o077); ROOT.mkdir(exist_ok=True, parents=True); ROOT.chmod(0o700)
    bank = prepare_bank(); fatura = prepare_fatura()
    # Manifest contains only hashes/IDs, not source content or invoice text.
    (HERE / 'manifest.json').write_text(json.dumps({'version': PROTOCOL['version'], 'bankstatemently': bank, 'fatura': fatura}, indent=2) + '\n')
    print(json.dumps({'bank_dev': len(PROTOCOL['bankstatemently']['dev']), 'fatura_train': sum(r['split']=='train' for r in fatura['documents']), 'fatura_dev': sum(r['split']=='dev' for r in fatura['documents']), 'reserved_extracted': 0}))


if __name__ == '__main__': main()
