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
CACHE_VERSION = 'embedding-v2'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cache_key(binary_hash, model_hashes, rows, variant, jobs):
    # A shard index has different rows when the job count changes.
    return hashlib.sha256(json.dumps([CACHE_VERSION, binary_hash, model_hashes, rows, variant, jobs], sort_keys=True).encode()).hexdigest()


def read_embeddings(out, expected_rows):
    meta = json.loads(Path(str(out) + '.json').read_text())
    dim = meta['dim']
    if type(dim) is not int or dim <= 0 or len(meta['items']) != expected_rows:
        raise ValueError('Native embed metadata has unexpected dimensions or row count')
    raw = np.fromfile(out, dtype='<f4')
    if raw.size != expected_rows * dim:
        raise ValueError('Native embed output rows have inconsistent dimensions')
    vec = raw.reshape(expected_rows, dim)
    found = []
    for v, item in zip(vec, meta['items'], strict=True):
        if type(item.get('found')) is not bool:
            raise ValueError('Native embed output is missing a detection flag')
        # A detected box with an absent mesh is not a usable face. The native
        # embed path historically labels these found; production photo does not.
        usable = item['found'] and item.get('presence', 1.0) >= 0.5
        norm = np.linalg.norm(v)
        usable = usable and np.isfinite(v).all() and np.isfinite(norm) and norm > 1e-12
        found.append(bool(usable))
    found = np.array(found, dtype=bool)
    vec[~found] = 0
    return vec, found, meta['items']


def capture_quality(rows, found, items):
    """Describe single-frame quality without claiming session capture success."""
    groups = {}
    for row, usable, item in zip(rows, found, items, strict=True):
        key = '/'.join((row['split'], row['pose'], row['condition']))
        group = groups.setdefault(key, {'frames': 0, 'usable_embeddings': 0, 'quality_score_one': 0})
        group['frames'] += 1
        group['usable_embeddings'] += int(usable)
        group['quality_score_one'] += int(usable and item.get('quality') == 1.)
    return {'groups': groups, 'interpretation': 'Native single-frame quality score, not capture BPCER; no session, guide, continuity or timing modeled; document photos do not use the live capture gate'}


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
    key = cache_key(digest(binary), {p.name: digest(p) for p in sorted(models.glob('*.onnx'))}, rows, variant, jobs)
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
        return read_embeddings(out, len(rows) * (i + 1) // jobs - len(rows) * i // jobs)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        parts = list(pool.map(run, range(jobs)))
    vec = np.concatenate([p[0] for p in parts])
    found = np.concatenate([p[1] for p in parts])
    vec /= np.maximum(np.linalg.norm(vec, axis=1, keepdims=True), 1e-12)
    items = [item for part in parts for item in part[2]]
    return vec, found, {'cache_key': key, 'elapsed_s': round(time.monotonic() - start, 2),
                        'capture_quality': capture_quality(rows, found, items)}


def scores(rows, vec, found, split, condition):
    a = [i for i, r in enumerate(rows) if r['split'] == split and r['pose'] == 'neutral' and r['condition'] == condition]
    b = [i for i, r in enumerate(rows) if r['split'] == split and r['pose'] == 'smile']
    s = vec[a] @ vec[b].T
    valid = found[a, None] & found[None, b]
    # Below every possible cosine threshold. Missing faces always reject,
    # even when all calibration references are missing.
    s[~valid] = -np.inf
    labels = np.array([[rows[i]['id'] == rows[j]['id'] for j in b] for i in a])
    return s, labels, {'identities': len(a), 'genuine_pairs': int(labels.sum()), 'impostor_pairs': int((~labels).sum()), 'missing_probe': int((~found[a]).sum()), 'missing_reference': int((~found[b]).sum())}


def threshold_at_far(s, y, far):
    # score >= threshold accepts. Step above a selected impostor to respect
    # the empirical FAR budget even with ties (no optimistic interpolation).
    if not 0 <= far < 1 or not np.any(~y):
        raise ValueError('Need impostor pairs and a FAR in [0, 1)')
    neg = np.sort(s[~y])[::-1]
    allowed = int(np.floor(far * len(neg)))
    cutoff = neg[allowed]
    if not np.isfinite(cutoff):
        return -1.0
    return float(np.nextafter(cutoff, np.array(np.inf, dtype=neg.dtype)))


def rates(s, y, t):
    if not np.any(y) or not np.any(~y):
        raise ValueError('Verification rates require genuine and impostor pairs')
    accepted = np.isfinite(s) & (s >= t)
    return {'tar': float(np.mean(accepted[y])), 'far': float(np.mean(accepted[~y])), 'genuine_accepted': int(accepted[y].sum()), 'impostors_accepted': int(accepted[~y].sum()), 'threshold': float(t)}


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
    p.add_argument('--variant', choices=('iris', 'flip', 'contour', 'nose4', 'inner-mouth', 'production-pair'), default='iris')
    p.add_argument('--jobs', type=int, choices=(1, 2), default=2)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    if not a.data.resolve().is_relative_to(Path('/tmp/docscan-public-data')):
        raise ValueError('Face data must stay owner-private in /tmp/docscan-public-data')
    rows = prepare(a.data)
    if a.variant == 'production-pair':
        vec, found, live_run = embed(a.binary.resolve(), a.data, rows, 'iris', a.jobs)
        still, still_found, photo_run = embed(a.binary.resolve(), a.data, rows, 'flip', a.jobs)
        mask = np.array([row['pose'] == 'neutral' for row in rows])
        vec[mask], found[mask] = still[mask], still_found[mask]
        run = {'unflipped_live': live_run, 'flip_averaged_photo': photo_run}
    else:
        vec, found, run = embed(a.binary.resolve(), a.data, rows, a.variant, a.jobs)
    report = {'protocol': 'london-neutral-smile-v1-dev-only', 'purpose': 'research evaluation; no training or shipped calibration', 'embedding_protocol': 'production-pair uses flip-averaged still vs unflipped reference; other variants use same transform on both; no session aggregation or quality gating', 'source_revision': json.loads((a.data / 'manifest.json').read_text())['revision'], 'source_manifest_sha256': digest(a.data / 'manifest.json'), 'protocol_sha256': digest(a.data / 'protocol-v1.json'), 'binary_sha256': digest(a.binary), 'variant': a.variant, 'models': {p.name: digest(p) for p in sorted((ROOT / 'models/face').glob('*.onnx'))}, 'run': run, 'metrics': score(rows, vec, found), 'limits': ['51 identities per split; 2550 dependent impostor pairs cannot certify population FAR=0.001', 'One photo session and source; no held-out device, age or source validation', 'Controlled portrait degradation is not physical ID capture', 'No attack data; APCER and liveness effectiveness not estimable', 'No model weights trained; no production threshold selected']}
    a.report.parent.mkdir(parents=True, exist_ok=True)
    report.update(protocol='london-neutral-smile-v2-dev-only', scorer_sha256=digest(Path(__file__)),
                  scorer_changes='Shard-aware cache; exact row counts; reject absent mesh and invalid embeddings; missing pairs always reject')
    a.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
