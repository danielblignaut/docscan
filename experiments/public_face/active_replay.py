#!/usr/bin/env python3
"""Attack-only active-session observation on five authorized replay previews.

This is not an active PAD accuracy benchmark: no bona fide challenge trials
exist here. Fixed sampling, original framing, default security configuration.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

from artifacts import pinned_run

import cv2

from pad_sample import DATA, REVISION, ROOT, digest, exact_interval

PROTOCOL = 'axon-active-replay-v1-attack-only'
EVERY = 3
LONG_SIDE = 960


def write_clip(source, destination):
    """Sequential decode, every third source frame; preserve nominal timestamps.

    The native tool buffers RGBA, so bound input size/duration explicitly. Each
    clip is evaluated sequentially. YUV conversion is a documented codec proxy.
    """
    video = cv2.VideoCapture(str(source))
    try:
        fps = video.get(cv2.CAP_PROP_FPS)
        count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        if not video.isOpened() or not math.isfinite(fps) or not 20 <= fps <= 60 or not 0 < count <= fps * 30:
            raise ValueError('Unexpected preview duration/rate; never truncate silently')
        rate = Fraction(fps / EVERY).limit_denominator(1_000_000)
        sampled, decoded = 0, 0
        with destination.open('wb') as out:
            for i in range(count):
                ok, frame = video.read()
                if not ok:
                    raise ValueError('Preview ended before its declared frame count')
                decoded += 1
                if i % EVERY:
                    continue
                h, w = frame.shape[:2]
                scale = min(1., LONG_SIDE / max(w, h))
                width, height = max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)
                if sampled == 0:
                    out.write(f'YUV4MPEG2 W{width} H{height} F{rate.numerator}:{rate.denominator} Ip A1:1 C420jpeg\n'.encode())
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
                out.write(b'FRAME\n')
                out.write(cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420).tobytes())
                sampled += 1
            if video.read()[0]:
                raise ValueError('Preview exceeded its declared frame count')
        return {'source_frames': decoded, 'sampled_frames': sampled, 'sample_fps': float(rate),
                'source_duration_s': count / fps, 'width': width, 'height': height}
    finally:
        video.release()


def summarize(runs):
    if not runs:
        raise ValueError('No attack trials')
    failed = Counter()
    phases = Counter()
    hints = Counter()
    accepted = completed = spoof_measured = parallax_measured = sweep_entered = 0
    thresholds = None
    for run in runs:
        result = run['result']
        checks = {c['name']: c for c in result['checks']}
        expected = {'coverage', '3d_motion', 'antispoof', 'continuity', 'identity'}
        if not expected <= checks.keys() or not all(checks[k]['required'] for k in expected):
            raise ValueError('Required physical/identity/PAD checks absent: invalid trial')
        current = {k: checks[k]['threshold'] for k in sorted(expected)}
        if thresholds is not None and thresholds != current:
            raise ValueError('Session thresholds changed across trials')
        thresholds = current
        decision = result['completed'] and all(c['passed'] for c in result['checks'] if c['required'])
        if type(result['passed']) is not bool or result['passed'] != decision:
            raise ValueError('Inconsistent native session decision')
        trace = run.get('trace')
        if not trace or len(trace) != result['frames']:
            raise ValueError('Missing or truncated native trace')
        accepted += result['passed']
        completed += result['completed']
        failed.update(k for k, c in checks.items() if c['required'] and not c['passed'])
        phases[trace[-1]['phase']] += 1
        hints.update(t['hint'] for t in trace)
        sweep_entered += any(t['phase'] in ('sweep', 'finish', 'done') for t in trace)
        spoof_measured += bool(run['antispoof'])
        parallax_measured += bool(run['parallax'])
    return {'attack_clips': len(runs), 'attacks_accepted': accepted,
            'observed_attack_acceptance_rate': accepted / len(runs),
            'attack_acceptance_iid_exact95': exact_interval(accepted, len(runs)),
            'completed_sessions': completed, 'entered_sweep': sweep_entered,
            'clips_with_passive_samples': spoof_measured, 'clips_with_parallax_samples': parallax_measured,
            'final_phases': dict(phases), 'failed_required_checks': dict(failed),
            'frame_hints': dict(hints), 'native_check_thresholds': thresholds,
            'bpcer': None, 'apcer_at_fixed_bpcer': None}


def evaluate(binary, report):
    with pinned_run(binary, ROOT / 'models/face') as artifacts:
        _evaluate(artifacts, report)


def _evaluate(artifacts, report):
    manifest_path = DATA / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    attacks = [r for r in manifest['files'] if r['class'] == 'replay']
    if manifest['revision'] != REVISION or len(attacks) != 5:
        raise ValueError('Expected the five pinned preview attacks')
    models = artifacts.model_hashes
    source_hash = digest(ROOT / 'docscan/src/face/liveness.rs')
    provenance = {'protocol': PROTOCOL, 'revision': REVISION, 'binary_sha256': artifacts.binary_sha256, 'artifact_guard_sha256': digest(Path(__file__).with_name('artifacts.py')),
                  'models': models, 'source_manifest_sha256': digest(manifest_path),
                  'scorer_sha256': digest(Path(__file__)), 'liveness_source_sha256': source_hash,
                  'opencv_version': cv2.__version__, 'every_source_frames': EVERY, 'long_side': LONG_SIDE,
                  'config_overrides': {}}
    key = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    folder = DATA / 'active-runs' / key
    folder.mkdir(parents=True, exist_ok=True)
    runs, metadata = [], []
    for index, attack in enumerate(attacks):
        source = DATA / attack['path']
        if digest(source) != attack['sha256']:
            raise ValueError('Pinned preview digest changed')
        output = folder / f'{index}.json'
        artifacts.verify()
        if not output.exists():
            clip = folder / f'{index}.y4m'
            try:
                info = write_clip(source, clip)
                info['clip_sha256'] = digest(clip)
                with artifacts.staged_output(output) as pending:
                    command = [str(artifacts.binary), '--models', str(artifacts.models_dir),
                               '--recogniser', 'sface_int8.onnx:sface_int8:sface', 'liveness', str(clip), '{}']
                    process = subprocess.run(command, env=dict(os.environ, TRACE='1', RTEN_NUM_THREADS='1', RAYON_NUM_THREADS='1'),
                                             check=True, timeout=600, capture_output=True, text=True)
                    result = json.loads(process.stdout)
                    result['sampling'] = info
                    summarize([result])
                    pending.write_text(json.dumps(result) + '\n')
            finally:
                clip.unlink(missing_ok=True)
        result = json.loads(output.read_text())
        runs.append(result)
        metadata.append(result['sampling'])
        print(f'Completed preview attack {index+1}/5', flush=True)
    result = {**provenance, 'metrics': summarize(runs),
              'sampling': {'source_duration_s_range': [min(m['source_duration_s'] for m in metadata), max(m['source_duration_s'] for m in metadata)],
                           'total_sampled_frames': sum(m['sampled_frames'] for m in metadata),
                           'derived_clips_sha256': hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()},
              'limits': ['Attack-only observation, not a controlled active PAD efficacy benchmark',
                         'No dynamic bona fide challenge videos: BPCER and APCER at fixed BPCER unavailable',
                         'Original framing; clips were not recorded following this ring challenge',
                         'Early quality/framing/coverage failures cannot prove physical or passive PAD efficacy',
                         'Every third source frame; nominal constant frame rate, not original variable timestamps',
                         'Downscaled and converted through YUV420; not browser/phone capture evidence',
                         'Five owner preview clips with unknown identity/device independence; no population/SOTA claim',
                         'Default thresholds, parallax and identity checks unchanged; no tuning or training']}
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
