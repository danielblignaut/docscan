#!/usr/bin/env python3
"""Fixed every-third-frame passive replay diagnostic; no new decision rule.

An any-frame crossing is an attack opportunity diagnostic, not the production
session decision. Original three-frame-median results remain separately reported.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess

from artifacts import pinned_run

import cv2
import numpy as np

from pad_sample import DATA, REVISION, ROOT, digest

PROTOCOL = 'axon-temporal-passive-v1-attack-only'
EVERY = 3
LONG_SIDE = 960


def frame_scores(output, expected):
    if len(output) != expected or expected <= 0:
        raise ValueError('Native output count differs from fixed frame count')
    values, missing, invalid = [], 0, 0
    for row in output:
        if type(row.get('found')) is not bool:
            raise ValueError('Native frame has no detection flag')
        value = row.get('raw_real')
        valid = row['found'] and isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1
        values.append(float(value) if valid else -1.)
        missing += not row['found']
        invalid += row['found'] and not valid
    return np.array(values), missing, invalid


def summarize(clips, thresholds):
    values = [frame_scores(c['scores'], c['frames']) for c in clips]
    if not values:
        raise ValueError('No replay trials')
    flat = np.concatenate([v[0] for v in values])
    metrics = {}
    for name, threshold in thresholds.items():
        accepted = [v[0] >= threshold for v in values]
        metrics[name] = {'raw_threshold': threshold,
                         'accepted_frames': int(sum(a.sum() for a in accepted)),
                         'sampled_frames': len(flat),
                         'frame_acceptance_fraction_descriptive': float(np.mean(flat >= threshold)),
                         'clips_with_any_accepted_frame': int(sum(a.any() for a in accepted)),
                         'clips_with_accepted_median': int(sum(np.median(v[0]) >= threshold for v in values)),
                         'attack_clips': len(clips)}
    return {'metrics': metrics, 'missing_frames': sum(v[1] for v in values),
            'invalid_frames': sum(v[2] for v in values), 'bpcer': None,
            'apcer_at_fixed_bpcer': None}


def evaluate(binary, report):
    with pinned_run(binary, ROOT / 'models/face') as artifacts:
        _evaluate(artifacts, report)


def _evaluate(artifacts, report):
    manifest = json.loads((DATA / 'manifest.json').read_text())
    attacks = [r for r in manifest['files'] if r['class'] == 'replay']
    if manifest['revision'] != REVISION or len(attacks) != 5:
        raise ValueError('Expected the five pinned preview attacks')
    provenance = {'protocol': PROTOCOL, 'source_revision': REVISION,
                  'source_manifest_sha256': digest(DATA / 'manifest.json'),
                  'binary_sha256': artifacts.binary_sha256, 'artifact_guard_sha256': digest(Path(__file__).with_name('artifacts.py')), 'scorer_sha256': digest(Path(__file__)),
                  'models': artifacts.model_hashes,
                  'opencv_version': cv2.__version__, 'every_source_frames': EVERY,
                  'long_side': LONG_SIDE}
    key = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    folder = DATA / 'temporal-runs' / key
    folder.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, attack in enumerate(attacks):
        source = DATA / attack['path']
        if digest(source) != attack['sha256']:
            raise ValueError('Pinned preview digest changed')
        output = folder / f'{index}.json'
        artifacts.verify()
        if not output.exists():
            video = cv2.VideoCapture(str(source))
            paths, hashes = [], []
            try:
                fps = video.get(cv2.CAP_PROP_FPS)
                count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
                if not video.isOpened() or not math.isfinite(fps) or not 20 <= fps <= 60 or not 0 < count <= fps * 30:
                    raise ValueError('Unexpected preview duration/rate')
                for i in range(count):
                    ok, frame = video.read()
                    if not ok:
                        raise ValueError('Truncated decode')
                    if i % EVERY:
                        continue
                    h, w = frame.shape[:2]
                    scale = min(1., LONG_SIDE / max(w, h))
                    frame = cv2.resize(frame, (round(w*scale), round(h*scale)), interpolation=cv2.INTER_AREA)
                    path = folder / f'{index}-{i}.png'
                    paths.append(path)
                    if not cv2.imwrite(str(path), frame):
                        raise ValueError('Could not write required frame')
                    hashes.append(digest(path))
                if video.read()[0]:
                    raise ValueError('Extra undeclared frames')
                listing = folder / f'{index}-images.txt'
                listing.write_text('\n'.join(map(str, paths)) + '\n')
                with artifacts.staged_output(output) as pending:
                    raw = pending.with_suffix('.raw.json')
                    subprocess.run([str(artifacts.binary), '--models', str(artifacts.models_dir), 'antispoof', str(listing), str(raw)],
                                   env=dict(os.environ, RTEN_NUM_THREADS='1', RAYON_NUM_THREADS='1'),
                                   check=True, timeout=600, capture_output=True)
                    scores = json.loads(raw.read_text())
                    frame_scores(scores, len(paths))
                    pending.write_text(json.dumps({'frames': len(paths), 'scores': scores, 'frame_hashes': hashes}) + '\n')
            finally:
                video.release()
                for path in paths:
                    path.unlink(missing_ok=True)
        clips.append(json.loads(output.read_text()))
        print(f'Completed temporal attack {index+1}/5', flush=True)
    constants = (ROOT / 'docscan/src/face/antispoof.rs').read_text()
    thresholds = {name: float(re.search(r'pub const ' + const + r': f32 = ([0-9.]+)', constants).group(1))
                  for name, const in [('passive', 'RAW_THRESHOLD'), ('session_passive_component', 'SESSION_RAW_THRESHOLD')]}
    result = {**provenance, **summarize(clips, thresholds),
              'derived_frames_sha256': hashlib.sha256(json.dumps([c['frame_hashes'] for c in clips]).encode()).hexdigest(),
              'limits': ['Attack-only temporal diagnostic; no bona fide temporal BPCER or calibrated operating point',
                         'Frame scores are correlated within clips; frame counts are not independent trials',
                         'Any-frame threshold crossing is not the production active-session decision',
                         'Only five owner preview attacks, unknown identities/devices; no population or SOTA claim',
                         'Original framing, no crop search, no threshold tuning, no physical check disabled',
                         'Fixed every-third-frame sample can miss events between sampled frames']}
    report.parent.mkdir(parents=True, exist_ok=True)
    artifacts.verify()
    report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.binary, args.report)
