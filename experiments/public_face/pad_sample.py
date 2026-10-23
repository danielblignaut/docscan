#!/usr/bin/env python3
"""Acquire/evaluate the owner's public replay sample; never train or calibrate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = Path('/tmp/docscan-public-data/face-axon-replay')
REVISION = 'f5560f659e185ded62c2f09ff502426b0588406e'
REPO = 'AxonData/Display_replay_attacks'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


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
    rows = []
    for index, media in enumerate(manifest['files']):
        source = DATA / media['path']
        if digest(source) != media['sha256']:
            raise ValueError('Source digest changed')
        if media['class'] == 'genuine':
            rows.append({'path': str(source), 'media': index, 'class': 'genuine', 'fraction': None})
            continue
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(source)], capture_output=True, text=True, check=True)
        duration = float(json.loads(probe.stdout)['format']['duration'])
        for fraction in (0.25, 0.5, 0.75):
            p = DATA / 'frames-v1' / f'{index}-{fraction}.png'
            p.parent.mkdir(exist_ok=True)
            if not p.exists():
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-ss', str(duration * fraction), '-i', str(source), '-frames:v', '1', '-vf', 'scale=960:960:force_original_aspect_ratio=decrease', '-threads', '1', str(p)], capture_output=True, check=True)
            rows.append({'path': str(p), 'media': index, 'class': 'replay', 'fraction': fraction})
    (DATA / 'protocol-v1.json').write_text(json.dumps(rows, indent=2) + '\n')
    return rows


def evaluate(binary, report):
    rows = prepare()
    folder = DATA / ('run-' + digest(binary))
    folder.mkdir(exist_ok=True)
    paths = folder / 'images.txt'
    paths.write_text('\n'.join(r['path'] for r in rows) + '\n')
    out = folder / 'scores.json'
    if not out.exists():
        subprocess.run([str(binary), '--models', str(ROOT / 'models/face'), 'antispoof', str(paths), str(out)], env=dict(os.environ, RTEN_NUM_THREADS='1', RAYON_NUM_THREADS='1'), check=True, timeout=300, capture_output=True)
    scores = json.loads(out.read_text())
    # Any failed frame has score -1 (rejection), never disappears from denominator.
    media = []
    for index in sorted({r['media'] for r in rows}):
        selected = [s for r, s in zip(rows, scores) if r['media'] == index]
        kind = next(r['class'] for r in rows if r['media'] == index)
        values = [s.get('raw_real', -1) for s in selected]
        media.append({'class': kind, 'score': float(np.median(values)), 'missing_frames': sum(not s['found'] for s in selected)})
    constants = (ROOT / 'docscan/src/face/antispoof.rs').read_text()
    thresholds = {name: float(re.search(r'pub const ' + const + r': f32 = ([0-9.]+)', constants).group(1)) for name, const in [('passive', 'RAW_THRESHOLD'), ('session_passive_component', 'SESSION_RAW_THRESHOLD')]}
    metrics = {}
    for name, threshold in thresholds.items():
        genuine = [m['score'] for m in media if m['class'] == 'genuine']
        attack = [m['score'] for m in media if m['class'] == 'replay']
        metrics[name] = {'raw_threshold': threshold, 'genuine_media': len(genuine), 'attack_media': len(attack), 'bpcer': float(np.mean(np.array(genuine) < threshold)), 'apcer': float(np.mean(np.array(attack) >= threshold))}
    result = {'protocol': 'axon-display-public-preview-v1', 'source_revision': REVISION, 'source_manifest_sha256': digest(DATA / 'manifest.json'), 'binary_sha256': digest(binary), 'model_sha256': digest(ROOT / 'models/face/minifasnet.onnx'), 'sample_unit': 'one genuine selfie or median of three fixed replay-video frames', 'frames': len(rows), 'missing_frames': sum(m['missing_frames'] for m in media), 'metrics': metrics, 'apcer_at_fixed_bpcer': None, 'limitations': ['Only five genuine photos and five attack videos; 20% error-rate steps', 'No verified identity mapping or held-out device split; no fitting or calibration', 'Still bona fide photos versus replay-video frames creates a media/source confound', 'Session threshold here evaluates passive component only, not active challenge/parallax', 'No dynamic bona fide videos, so active-session BPCER cannot be measured', 'No claim of SOTA, certification, or representative commercial accuracy']}
    report.parent.mkdir(parents=True, exist_ok=True)
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
