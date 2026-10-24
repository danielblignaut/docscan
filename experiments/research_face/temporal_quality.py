#!/usr/bin/env python3
"""Frozen DEV replay fusion diagnostic; cached inference, fresh pixel processing."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

import cv2
import numpy as np

ROOT = Path('/home/dan/scratch/id-scan-spike')
DATA = Path('/tmp/docscan-public-data/face-axon-replay')
PRIVATE = Path('/tmp/docscan-public-data/research-face')
OWN = ROOT / 'experiments/research_face'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def frame_values(rows):
    values, missing, invalid = [], 0, 0
    for row in rows:
        if type(row.get('found')) is not bool:
            raise ValueError('Missing detection flag')
        value = row.get('raw_real')
        good = (row['found'] and type(value) in (float, int)
                and math.isfinite(value) and 0 <= value <= 1)
        values.append(float(value) if good else -1.)
        missing += not row['found']
        invalid += row['found'] and not good
    return np.asarray(values), missing, invalid


def fuse(scores, weights, times, cfg):
    scores, weights, times = map(np.asarray, (scores, weights, times))
    if not len(scores) or not (scores.shape == weights.shape == times.shape):
        raise ValueError('Mismatched/empty denominator')
    if (not all(np.isfinite(x).all() for x in (scores, weights, times))
            or np.any(weights <= 0) or np.any(np.diff(times) <= 0)
            or np.any(times < 0) or np.any(scores < -1) or np.any(scores > 1)):
        raise ValueError('Invalid temporal input')
    blocks = np.floor(times / cfg['sampling']['block_seconds']).astype(int)
    if not np.array_equal(np.unique(blocks), np.arange(blocks[-1] + 1)):
        raise ValueError('Missing temporal block')
    means, quality_means, sizes = [], [], []
    for block in np.unique(blocks):
        mask = blocks == block
        means.append(float(np.mean(scores[mask])))
        quality_means.append(float(np.average(scores[mask], weights=weights[mask])))
        sizes.append(int(mask.sum()))
    q = lambda x: float(np.quantile(x, cfg['quantile'], method=cfg['quantile_method']))
    return {'frame_median': float(np.median(scores)), 'frame_q10': q(scores),
            'block_mean_q10': q(means), 'block_quality_mean_q10': q(quality_means)}, sizes


def sharpness_weight(frame, cfg):
    q = cfg['quality']
    h, w = frame.shape[:2]
    margin = (1 - q['roi_fraction']) / 2
    crop = frame[int(h*margin):int(h*(1-margin)), int(w*margin):int(w*(1-margin))]
    gray = cv2.cvtColor(cv2.resize(crop, (q['side'], q['side']), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return max(q['floor'], variance / (variance + q['saturation']))


def verify_models(prior):
    for name, expected in prior['models'].items():
        if digest(ROOT / 'models/face' / name) != expected:
            raise ValueError('Model bytes differ from frozen inference')


def evaluate(folder):
    cfg = json.loads((folder / 'protocol-v1.json').read_text())
    freeze = json.loads((folder / 'freeze.json').read_text())
    if digest(Path(__file__)) != freeze['runner_sha256'] or digest(folder / 'protocol-v1.json') != freeze['config_sha256']:
        raise ValueError('Frozen source changed')
    prior_path = ROOT / cfg['prior_report']
    prior = json.loads(prior_path.read_text())
    manifest = json.loads((DATA / 'manifest.json').read_text())
    if digest(DATA / 'manifest.json') != prior['source_manifest_sha256'] or manifest['revision'] != cfg['source_revision']:
        raise ValueError('Preview provenance mismatch')
    if cv2.__version__ != prior['opencv_version']:
        raise ValueError('Decoder version differs from original frame hashes')
    verify_models(prior)
    attacks = [row for row in manifest['files'] if row['class'] == 'replay']
    if len(attacks) != 5:
        raise ValueError('Exactly five DEV attacks required')
    private, frame_hashes, cache_hashes = [], [], {}
    for index, attack in enumerate(attacks):
        source = DATA / attack['path']
        if digest(source) != attack['sha256']:
            raise ValueError('Source media hash changed')
        cache_path = DATA / 'temporal-runs' / cfg['prior_cache'] / f'{index}.json'
        cache_hashes[str(index)] = digest(cache_path)
        cached = json.loads(cache_path.read_text())
        scores, missing, invalid = frame_values(cached['scores'])
        if len(scores) != cached['frames'] or len(scores) != len(cached['frame_hashes']):
            raise ValueError('Cached row mismatch')
        video = cv2.VideoCapture(str(source))
        weights, times, hashes = [], [], []
        try:
            fps = video.get(cv2.CAP_PROP_FPS)
            count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
            if not video.isOpened() or not math.isfinite(fps) or not 20 <= fps <= 60 or not 0 < count <= fps*30:
                raise ValueError('Unexpected duration/rate')
            for n in range(count):
                ok, frame = video.read()
                if not ok:
                    raise ValueError('Truncated clip')
                if n % cfg['sampling']['every_source_frames']:
                    continue
                h, w = frame.shape[:2]
                scale = min(1., cfg['sampling']['long_side']/max(w, h))
                frame = cv2.resize(frame, (round(w*scale), round(h*scale)), interpolation=cv2.INTER_AREA)
                ok, encoded = cv2.imencode('.png', frame)
                if not ok:
                    raise ValueError('PNG hash encoding failed')
                hashes.append(hashlib.sha256(encoded.tobytes()).hexdigest())
                weights.append(sharpness_weight(frame, cfg))
                times.append(n / fps)
            if video.read()[0]:
                raise ValueError('Undeclared extra frames')
        finally:
            video.release()
        if hashes != cached['frame_hashes'] or len(scores) != len(weights):
            raise ValueError('Decoded frames do not match frozen inference')
        frame_hashes.append(hashes)
        fused, sizes = fuse(scores, weights, times, cfg)
        private.append({'ordinal': index, 'source_sha256': attack['sha256'],
                        'fps': fps, 'source_frames': count, 'sampled_frames': len(scores),
                        'missing_frames': missing, 'invalid_frames': invalid,
                        'block_sizes': sizes, 'scores': scores.tolist(), 'weights': weights,
                        'timestamps': times, 'fused_scores': fused})
        print(f'Checked replay {index + 1}/5: {len(scores)} frames', flush=True)
    combined_hash = hashlib.sha256(json.dumps(frame_hashes).encode()).hexdigest()
    if combined_hash != prior['derived_frames_sha256']:
        raise ValueError('Combined frame provenance mismatch')
    # Reproduce the prior aggregate before publishing a new comparison.
    flat = np.concatenate([np.asarray(row['scores']) for row in private])
    for label, old in prior['metrics'].items():
        if int((flat >= old['raw_threshold']).sum()) != old['accepted_frames'] or len(flat) != old['sampled_frames']:
            raise ValueError('Cached scores do not reproduce original report')
    metrics = {}
    for candidate in cfg['candidates']:
        values = np.asarray([row['fused_scores'][candidate] for row in private])
        reference = np.asarray([row['fused_scores']['frame_q10'] for row in private])
        metrics[candidate] = {'attack_clips': 5, 'sampled_frames': len(flat),
                             'min_score': float(values.min()), 'median_score': float(np.median(values)),
                             'max_score': float(values.max()),
                             'clips_score_increases_vs_frame_q10': int((values > reference + 1e-12).sum()),
                             'max_score_increase_vs_frame_q10': float(np.max(values-reference)),
                             'thresholds': {name: {'raw_threshold': t, 'accepted_attack_clips': int((values >= t).sum()), 'denominator': 5} for name, t in cfg['thresholds'].items()}}
    result = {'protocol': cfg['protocol'], 'finished_utc': datetime.now(timezone.utc).isoformat(),
              'freeze': freeze, 'original_inference_binary_sha256': prior['binary_sha256'],
              'original_report_sha256': digest(prior_path), 'models': prior['models'],
              'source_manifest_sha256': digest(DATA/'manifest.json'),
              'source_revision': cfg['source_revision'], 'private_cache_sha256': cache_hashes,
              'derived_frames_sha256': combined_hash, 'numpy_version': np.__version__,
              'opencv_version': cv2.__version__, 'sampled_frames': len(flat),
              'missing_frames': sum(r['missing_frames'] for r in private),
              'invalid_frames': sum(r['invalid_frames'] for r in private),
              'block_count': sum(len(r['block_sizes']) for r in private),
              'minimum_block_frames': min(min(r['block_sizes']) for r in private),
              'metrics': metrics, 'bona_fide_temporal_trials': 0, 'bpcer': None,
              'active_apcer': None, 'apcer_at_fixed_bpcer': None,
              'private_results_path': str(folder/'per-clip.json'),
              'limits': ['Cached native inference plus fresh pixel processing; not new inference',
                         'Attack-only, five correlated/unknown-identity-device preview trials',
                         'No temporal bona fide trials, no active challenge efficacy or population inference',
                         'Central image sharpness is not localized face utility or spoof evidence',
                         'One-second blocks use nominal source fps; no variable-rate device timing evidence',
                         'Raw offline aggregates are not production session outcomes',
                         'All candidates retained; no fitted parameter, threshold, weight or acceptance change']}
    verify_models(prior)
    write_new(folder/'per-clip.json', private)
    result['private_results_sha256'] = digest(folder/'per-clip.json')
    write_new(OWN/'results/temporal-quality-v1.json', result)
    print(json.dumps(metrics, indent=2))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen-folder', type=Path)
    args = parser.parse_args()
    if args.frozen_folder:
        evaluate(args.frozen_folder)
        return
    config = OWN/'protocol-v1.json'
    key = hashlib.sha256((digest(config)+digest(Path(__file__))).encode()).hexdigest()
    folder = PRIVATE/key
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(config, folder/'protocol-v1.json')
    shutil.copyfile(Path(__file__), folder/'temporal_quality.py')
    write_new(folder/'freeze.json', {'frozen_utc': datetime.now(timezone.utc).isoformat(),
                                   'config_sha256': digest(config), 'runner_sha256': digest(Path(__file__)),
                                   'base_commit': json.loads(config.read_text())['base_commit']})
    subprocess.run([sys.executable, str(folder/'temporal_quality.py'), '--frozen-folder', str(folder)], check=True)


if __name__ == '__main__':
    main()
