#!/usr/bin/env python3
"""Identity-disjoint research DEV: real neutral/smile pairs and document-photo stress.

No TEST data is read or generated. A new identity-disjoint DEV validation slice
is deliberately not called a lockbox. All biometric outputs remain in /tmp.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import time

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
DATA = Path('/tmp/docscan-public-data/face-london')
CONDITIONS = ('original', 'document_gray', 'document_small')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(data):
    manifest = json.loads((data / 'manifest.json').read_text())
    files = manifest['files']
    for row in files:
        if digest(data / row['path']) != row['sha256']:
            raise ValueError('Downloaded source changed')
    sources = {p['path'].split('/')[-2]: {} for p in files}
    for row in files:
        p = Path(row['path'])
        sources[p.parent.name][p.stem.split('_')[0]] = data / p
    identities = sorted(set(sources['neutral_front']) & set(sources['smiling_front']), key=lambda x: hashlib.sha256(('london-dev-v1:' + x).encode()).hexdigest())
    if len(identities) != 102:
        raise ValueError('Expected 102 complete identities')
    rows = []
    for number, identity in enumerate(identities):
        split = 'calibration' if number < 51 else 'validation'
        for pose, source in [('neutral', sources['neutral_front'][identity]), ('smile', sources['smiling_front'][identity])]:
            conditions = CONDITIONS if pose == 'neutral' else ('original',)
            for condition in conditions:
                p = source
                if condition != 'original':
                    p = data / 'derived-v1' / f'{identity}-{condition}.jpg'
                    if not p.exists():
                        # This is a controlled portrait stress, not a physical ID capture.
                        im = Image.open(source).convert('RGB')
                        side = 384 if condition == 'document_gray' else 192
                        im = im.resize((side, side), Image.Resampling.LANCZOS).convert('L').convert('RGB')
                        im = im.filter(ImageFilter.GaussianBlur(0.4 if side == 384 else 0.7))
                        p.parent.mkdir(exist_ok=True)
                        im.save(p, quality=65 if side == 384 else 45)
                rows.append({'id': identity, 'split': split, 'pose': pose, 'condition': condition, 'path': str(p), 'sha256': digest(p)})
    (data / 'protocol-v1.json').write_text(json.dumps(rows, indent=2) + '\n')
    return rows


def embed(binary, data, rows, variant, jobs):
    flags = []
    if variant == 'flip':
        flags = ['--flip']
    elif variant != 'iris':
        flags = ['--align', variant]
    models = ROOT / 'models/face'
    key = hashlib.sha256((digest(binary) + variant + ''.join(digest(p) for p in sorted(models.glob('*.onnx'))) + json.dumps(rows)).encode()).hexdigest()
    folder = data / 'runs' / key
    folder.mkdir(parents=True, exist_ok=True)
    paths = folder / 'images.txt'
    paths.write_text('\n'.join(row['path'] for row in rows) + '\n')
    env = dict(os.environ, RTEN_NUM_THREADS='1', RAYON_NUM_THREADS='1')
    start = time.monotonic()

    def run(i):
        out = folder / f'{i}.f32'
        if not out.exists() or not Path(str(out) + '.json').exists():
            cmd = [str(binary), '--models', str(models), '--recogniser', 'sface_int8.onnx:sface_int8:sface', '--no-antispoof', 'embed', str(paths), str(out), '--shard', f'{i}/{jobs}', *flags]
            subprocess.run(cmd, env=env, check=True, timeout=1200, capture_output=True)
        meta = json.loads(Path(str(out) + '.json').read_text())
        raw = np.fromfile(out, dtype='<f4')
        # Native harness has a historical zero-length-row bug if first face fails.
        # Refuse to reshape silently; never score a displaced person's embedding.
        if raw.size != len(meta['items']) * meta['dim']:
            raise ValueError('Native embed output rows have inconsistent dimensions')
        return raw.reshape(-1, meta['dim']), meta['items']

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        parts = list(pool.map(run, range(jobs)))
    vec = np.concatenate([p[0] for p in parts])
    found = np.array([x['found'] for p in parts for x in p[1]])
    vec /= np.maximum(np.linalg.norm(vec, axis=1, keepdims=True), 1e-12)
    return vec, found, {'cache_key': key, 'elapsed_s': round(time.monotonic() - start, 2)}


def scores(rows, vec, found, split, condition):
    a = [i for i, r in enumerate(rows) if r['split'] == split and r['pose'] == 'neutral' and r['condition'] == condition]
    b = [i for i, r in enumerate(rows) if r['split'] == split and r['pose'] == 'smile']
    s = vec[a] @ vec[b].T
    valid = found[a, None] & found[None, b]
    s[~valid] = -1
    labels = np.array([[rows[i]['id'] == rows[j]['id'] for j in b] for i in a])
    return s, labels, {'identities': len(a), 'genuine_pairs': int(labels.sum()), 'impostor_pairs': int((~labels).sum()), 'missing_probe': int((~found[a]).sum()), 'missing_reference': int((~found[b]).sum())}


def threshold_at_far(s, y, far):
    # score >= threshold accepts. Step above a selected impostor to respect
    # the empirical FAR budget even with ties (no optimistic interpolation).
    neg = np.sort(s[~y])[::-1]
    allowed = int(np.floor(far * len(neg)))
    return float(np.nextafter(neg[min(allowed, len(neg) - 1)], np.float32(np.inf)))


def rates(s, y, t):
    return {'tar': float(np.mean(s[y] >= t)), 'far': float(np.mean(s[~y] >= t)), 'threshold': float(t)}


def score(rows, vec, found):
    output = {}
    live_source = (ROOT / 'docscan/src/face/mod.rs').read_text()
    doc_source = (ROOT / 'demo/src/face-models.ts').read_text()
    live_threshold = float(re.search(r'model: \"sface_int8\", threshold: ([0-9.]+)', live_source).group(1))
    doc_threshold = float(re.search(r'DOC_THRESHOLD = ([0-9.]+)', doc_source).group(1))
    for condition in CONDITIONS:
        cs, cy, ci = scores(rows, vec, found, 'calibration', condition)
        vs, vy, vi = scores(rows, vec, found, 'validation', condition)
        shipped = live_threshold if condition == 'original' else doc_threshold
        result = {'calibration_counts': ci, 'validation_counts': vi, 'shipped_threshold': {'calibration': rates(cs, cy, shipped), 'validation': rates(vs, vy, shipped)}}
        for far in (0.001, 0.01):
            t = threshold_at_far(cs, cy, far)
            result[f'calibrated_far_{far}'] = {'calibration': rates(cs, cy, t), 'validation': rates(vs, vy, t)}
        output[condition] = result
    return output


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, default=DATA)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--variant', choices=('iris', 'flip', 'contour', 'nose4', 'inner-mouth'), default='iris')
    p.add_argument('--jobs', type=int, choices=(1, 2), default=2)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    if not a.data.resolve().is_relative_to(Path('/tmp/docscan-public-data')):
        raise ValueError('Face data must stay owner-private in /tmp/docscan-public-data')
    rows = prepare(a.data)
    vec, found, run = embed(a.binary.resolve(), a.data, rows, a.variant, a.jobs)
    report = {'protocol': 'london-neutral-smile-v1-dev-only', 'purpose': 'research evaluation; no training or shipped calibration', 'source_revision': json.loads((a.data / 'manifest.json').read_text())['revision'], 'source_manifest_sha256': digest(a.data / 'manifest.json'), 'protocol_sha256': digest(a.data / 'protocol-v1.json'), 'binary_sha256': digest(a.binary), 'variant': a.variant, 'models': {p.name: digest(p) for p in sorted((ROOT / 'models/face').glob('*.onnx'))}, 'run': run, 'metrics': score(rows, vec, found), 'limits': ['51 identities per split; 2550 dependent impostor pairs cannot certify population FAR=0.001', 'One photo session and source; no held-out device, age or source validation', 'Controlled portrait degradation is not physical ID capture', 'No attack data; APCER and liveness effectiveness not estimable', 'No model weights trained; no production threshold selected']}
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
