#!/usr/bin/env python3
"""Acquire/evaluate the owner's public replay sample; never train or calibrate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = Path('/tmp/docscan-public-data/face-axon-replay')
REVISION = 'f5560f659e185ded62c2f09ff502426b0588406e'
REPO = 'AxonData/Display_replay_attacks'
PROTOCOL = 'axon-display-public-preview-v2'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_key(binary_hash, models, rows):
    return hashlib.sha256(json.dumps([PROTOCOL, binary_hash, models, rows], sort_keys=True).encode()).hexdigest()


def exact_interval(errors, total):
    """Two-sided Clopper-Pearson 95% interval, assuming independent trials.

    Preview identities/devices may repeat: this is a sample-size illustration,
    not a population-accuracy guarantee. Small n only; no asymptotic interval.
    """
    if not 0 <= errors <= total or total <= 0:
        raise ValueError('Invalid binomial counts')

    def inverse_cdf(k, target):
        lo, hi = 0., 1.
        for _ in range(60):
            p = (lo + hi) / 2
            cdf = sum(math.comb(total, i) * p**i * (1-p)**(total-i) for i in range(k + 1))
            if cdf > target:
                lo = p
            else:
                hi = p
        return (lo + hi) / 2

    return [0. if errors == 0 else inverse_cdf(errors - 1, .975),
            1. if errors == total else inverse_cdf(errors, .025)]


def media_scores(rows, scores):
    if len(rows) != len(scores):
        raise ValueError('Native PAD output count does not match the fixed protocol')
    frame_scores = []
    for s in scores:
        if type(s.get('found')) is not bool:
            raise ValueError('Native PAD output is missing a detection flag')
        value = s.get('raw_real')
        valid = s['found'] and isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1
        # Missing/non-finite frames reject, even if a stray raw score exists.
        frame_scores.append((float(value) if valid else -1., not s['found'], s['found'] and not valid))
    media = []
    for index in sorted({r['media'] for r in rows}):
        selected = [s for r, s in zip(rows, frame_scores, strict=True) if r['media'] == index]
        kinds = {r['class'] for r in rows if r['media'] == index}
        if len(kinds) != 1 or not kinds <= {'genuine', 'replay'}:
            raise ValueError('Invalid media labels')
        media.append({'class': kinds.pop(), 'score': float(np.median([s[0] for s in selected])),
                      'missing_frames': sum(s[1] for s in selected), 'invalid_frames': sum(s[2] for s in selected)})
    if not any(m['class'] == 'genuine' for m in media) or not any(m['class'] == 'replay' for m in media):
        raise ValueError('PAD requires both classes')
    return media


def fetch():
    DATA.mkdir(parents=True, exist_ok=True)
    DATA.chmod(0o700)
    tree = json.load(urllib.request.urlopen(f'https://huggingface.co/api/datasets/{REPO}/tree/{REVISION}?recursive=true', timeout=60))
    files = [f for f in tree if f['type'] == 'file' and f['path'].lower().endswith(('.jpg', '.mp4', '.mov'))]
    if len(files) != 10 or sum(f['size'] for f in files) > 200_000_000:
        raise ValueError('Unexpected pinned release')

    def one(f):
        p = DATA / f['path']
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            url = f'https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/' + urllib.parse.quote(f['path'])
            with urllib.request.urlopen(url, timeout=120) as source, p.open('wb') as out:
                total = 0
                while block := source.read(1024 * 1024):
                    total += len(block)
                    if total > f['size']:
                        raise ValueError('Download exceeded declared bound')
                    out.write(block)
        if p.stat().st_size != f['size'] or digest(p) != f['lfs']['oid']:
            p.unlink(missing_ok=True)
            raise ValueError('Pinned SHA-256 verification failed')
        return {'path': f['path'], 'bytes': f['size'], 'sha256': f['lfs']['oid'], 'class': 'genuine' if '/Real/' in f['path'] else 'replay'}

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(one, files))
    notice = urllib.request.urlopen(f'https://huggingface.co/datasets/{REPO}/raw/{REVISION}/README.md', timeout=60).read()
    (DATA / 'source-README.md').write_bytes(notice)
    # Preserve the owner's broader terms as well as the sample card: a license
    # tag alone does not resolve consent or the full collection's restrictions.
    notices = {
        'official-github': 'https://raw.githubusercontent.com/axonlab-data/face-anti-spoofing-dataset/e0c8bf8d0b3419806825bbc319575c05a17ca240/README.md',
        'liveness-evaluation': 'https://huggingface.co/datasets/AxonData/liveness-detection-dataset/raw/c28f25c20328748b77c794853134e009df3b36fa/README.md',
    }
    for name, url in notices.items():
        (DATA / ('source-' + name + '-README.md')).write_bytes(urllib.request.urlopen(url, timeout=60).read())
    manifest = {'source': f'https://huggingface.co/datasets/{REPO}/tree/{REVISION}', 'revision': REVISION, 'provider': 'Axon Labs', 'license_tag': 'CC-BY-4.0', 'scope': 'public owner-provided evaluation preview; full collection commercially licensed; no training or redistribution', 'files': rows, 'source_notices': {name: {'url': url, 'sha256': digest(DATA / ('source-' + name + '-README.md'))} for name, url in notices.items()}}
    (DATA / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'files': len(rows), 'bytes': sum(r['bytes'] for r in rows)}))


def prepare():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    if len(manifest['files']) != 10 or sum(m['class'] == 'genuine' for m in manifest['files']) != 5:
        raise ValueError('Expected the pinned five genuine and five replay media')
    rows = []
    for index, media in enumerate(manifest['files']):
        source = DATA / media['path']
        if digest(source) != media['sha256']:
            raise ValueError('Source digest changed')
        if media['class'] == 'genuine':
            rows.append({'path': str(source), 'sha256': digest(source), 'media': index, 'class': 'genuine', 'fraction': None})
            continue
        video = cv2.VideoCapture(str(source))
        count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        if not video.isOpened() or count <= 0:
            raise ValueError('Video could not be decoded')
        for fraction in (0.25, 0.5, 0.75):
            p = DATA / 'frames-v1' / f'{index}-{fraction}.png'
            p.parent.mkdir(exist_ok=True)
            if not p.exists():
                video.set(cv2.CAP_PROP_POS_FRAMES, int(count * fraction))
                ok, frame = video.read()
                if not ok:
                    raise ValueError('Required frame unavailable; never skip silently')
                h, w = frame.shape[:2]
                scale = min(1.0, 960 / max(w, h))
                frame = cv2.resize(frame, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
                if not cv2.imwrite(str(p), frame):
                    raise ValueError('Could not write decoded frame')
            rows.append({'path': str(p), 'sha256': digest(p), 'media': index, 'class': 'replay', 'fraction': fraction})
        video.release()
    (DATA / 'protocol-v2.json').write_text(json.dumps(rows, indent=2) + '\n')
    return rows


def evaluate(binary, report):
    rows = prepare()
    models = {p.name: digest(p) for p in sorted((ROOT / 'models/face').glob('*.onnx'))}
    folder = DATA / ('run-' + run_key(digest(binary), models, rows))
    folder.mkdir(exist_ok=True)
    paths = folder / 'images.txt'
    paths.write_text('\n'.join(r['path'] for r in rows) + '\n')
    out = folder / 'scores.json'
    if not out.exists():
        subprocess.run([str(binary), '--models', str(ROOT / 'models/face'), 'antispoof', str(paths), str(out)], env=dict(os.environ, RTEN_NUM_THREADS='1', RAYON_NUM_THREADS='1'), check=True, timeout=300, capture_output=True)
    scores = json.loads(out.read_text())
    media = media_scores(rows, scores)
    constants = (ROOT / 'docscan/src/face/antispoof.rs').read_text()
    thresholds = {name: float(re.search(r'pub const ' + const + r': f32 = ([0-9.]+)', constants).group(1)) for name, const in [('passive', 'RAW_THRESHOLD'), ('session_passive_component', 'SESSION_RAW_THRESHOLD')]}
    metrics = {}
    for name, threshold in thresholds.items():
        genuine = [m['score'] for m in media if m['class'] == 'genuine']
        attack = [m['score'] for m in media if m['class'] == 'replay']
        metrics[name] = {'raw_threshold': threshold, 'genuine_media': len(genuine), 'attack_media': len(attack), 'bpcer': float(np.mean(np.array(genuine) < threshold)), 'apcer': float(np.mean(np.array(attack) >= threshold))}
        metrics[name]['genuine_rejected'] = int(sum(s < threshold for s in genuine))
        metrics[name]['attacks_accepted'] = int(sum(s >= threshold for s in attack))
        metrics[name]['bpcer_iid_exact95'] = exact_interval(metrics[name]['genuine_rejected'], len(genuine))
        metrics[name]['apcer_iid_exact95'] = exact_interval(metrics[name]['attacks_accepted'], len(attack))
    result = {'protocol': 'axon-display-public-preview-v1', 'source_revision': REVISION, 'opencv_version': cv2.__version__, 'source_manifest_sha256': digest(DATA / 'manifest.json'), 'binary_sha256': digest(binary), 'model_sha256': digest(ROOT / 'models/face/minifasnet.onnx'), 'sample_unit': 'one genuine selfie or median of three fixed replay-video frames', 'frames': len(rows), 'missing_frames': sum(m['missing_frames'] for m in media), 'metrics': metrics, 'apcer_at_fixed_bpcer': None, 'limitations': ['Only five genuine photos and five attack videos; 20% error-rate steps', 'No verified identity mapping or held-out device split; no fitting or calibration', 'Still bona fide photos versus replay-video frames creates a media/source confound', 'Session threshold here evaluates passive component only, not active challenge/parallax', 'No dynamic bona fide videos, so active-session BPCER cannot be measured', 'No claim of SOTA, certification, or representative commercial accuracy']}
    report.parent.mkdir(parents=True, exist_ok=True)
    result.update(protocol=PROTOCOL, protocol_sha256=digest(DATA / 'protocol-v2.json'), models=models,
                  scorer_sha256=digest(Path(__file__)), invalid_frames=sum(m['invalid_frames'] for m in media))
    result['limitations'].append('Exact intervals assume independent media, unverified here; descriptive only')
    report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('fetch', 'evaluate'))
    p.add_argument('--binary', type=Path)
    p.add_argument('--report', type=Path)
    args = p.parse_args()
    if args.command == 'fetch':
        fetch()
    else:
        if not args.binary or not args.report:
            p.error('evaluate requires --binary and --report')
        evaluate(args.binary.resolve(), args.report)
