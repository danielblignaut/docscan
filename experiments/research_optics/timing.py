#!/usr/bin/env python3
"""Separate, sequential paired timing; descriptive native feasibility, not WASM."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image

from optics import preprocess, diagnostic
from run import HERE, REPO, native, sha, write


def calibration():
    payload = bytes(64 * 1024 * 1024)
    times = []
    for _ in range(3):
        start = time.perf_counter()
        hashlib.sha256(payload).digest()
        times.append((time.perf_counter()-start)*1000)
    return float(np.median(times))


def bootstrap(ratios):
    rng = np.random.default_rng(81)
    draws = np.median(rng.choice(ratios, size=(2000, len(ratios))), axis=1)
    return [float(v) for v in np.percentile(draws, [2.5, 97.5])]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', type=Path, default=HERE/'results-v1.json')
    p.add_argument('--output', type=Path, default=HERE/'timing-v1.json')
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('refusing overwrite')
    os.umask(0o077)
    report = json.loads(a.results.read_text())
    run = Path(report['private_run'])
    frozen = json.loads((run/'freeze.json').read_text())
    if sha(run/'freeze.json') != report['freeze_sha256']:
        raise ValueError('changed freeze')
    for path, digest in frozen['source_hashes'].items():
        if sha(REPO/path) != digest:
            raise ValueError('changed source')
    assets = frozen['assets']
    for entry in assets.values():
        if sha(entry['path']) != entry['sha256']:
            raise ValueError('changed assets')
    manifest = json.loads((REPO/'experiments/public_documents/ocr-dev-v1.json').read_text())
    selected = []
    seen = set()
    for index, row in enumerate(manifest['samples']):
        ident = row['id']
        group = ident.split('_Instance')[0] if row['source'] == 'fatura' else ident.rsplit('-p', 1)[0]
        if group not in seen:
            seen.add(group)
            selected.append(index)
    assert len(selected) == 8
    cpu = sorted(os.sched_getaffinity(0))[-1]
    os.sched_setaffinity(0, {cpu})
    (run/'timing').mkdir()
    receipt = {'frozen_utc': datetime.now(timezone.utc).isoformat(), 'accuracy_report_sha256': sha(a.results),
               'timing_source_sha256': sha(__file__), 'sample_indices': selected, 'repeats': 3,
               'cpu': cpu, 'load_before': os.getloadavg(), 'condition': 'dark',
               'order': 'candidate/baseline alternates by sample index and repeat; separate pair for each candidate'}
    write(run/'timing/freeze.json', receipt)
    inputs = {e['index']: frozen['unique_inputs'][e['key']] for e in frozen['documents']
              if e['condition'] == 'dark' and e['arm'] == 'baseline' and e['index'] in selected}
    data = {i: np.asarray(Image.open(e['path']).convert('RGB')) for i, e in inputs.items()}
    # One baseline warm-up, excluded symmetrically from paired measurements.
    native(inputs[selected[0]]['path'], 'ocr', assets)
    rows = []
    for repeat in range(3):
        before = calibration()
        pending = []
        for index in selected:
            for candidate in ('global_exposure', 'local_illumination'):
                order = ['baseline', candidate]
                if (selected.index(index)+repeat) % 2:
                    order.reverse()
                pair = {'index': index, 'repeat': repeat, 'candidate': candidate}
                for arm in order:
                    start = time.perf_counter()
                    pixels, _ = preprocess(data[index], arm)
                    preprocess_ms = (time.perf_counter()-start)*1000
                    path = run/'timing'/f'{index}-{repeat}-{candidate}-{arm}.png'
                    Image.fromarray(pixels).save(path)
                    output = native(path, 'ocr', assets)
                    pair[arm] = {'total_ms': (time.perf_counter()-start)*1000,
                                 'preprocess_ms': preprocess_ms, 'native_ms': output['native_ms'],
                                 'failure': output['failure']}
                pending.append(pair)
        after = calibration()
        # Both adjacent arms share the same bracket calibration; retain it rather
        # than using host drift to invent a speed improvement.
        for pair in pending:
            pair['calibration_before_ms'] = before
            pair['calibration_after_ms'] = after
        rows.extend(pending)
        print(json.dumps({'timing_repeat_completed': repeat+1}), flush=True)
    summary = {}
    for candidate in ('global_exposure', 'local_illumination'):
        part = [r for r in rows if r['candidate'] == candidate]
        per_group_ratios = [float(np.median([r[candidate]['total_ms']/r['baseline']['total_ms'] for r in part if r['index'] == i])) for i in selected]
        summary[candidate] = {'paired_groups': 8, 'paired_runs': len(part),
            'baseline_median_ms': float(np.median([r['baseline']['total_ms'] for r in part])),
            'candidate_median_ms': float(np.median([r[candidate]['total_ms'] for r in part])),
            'candidate_preprocess_median_ms': float(np.median([r[candidate]['preprocess_ms'] for r in part])),
            'median_paired_ratio': float(np.median(per_group_ratios)), 'bootstrap_95_ci': bootstrap(per_group_ratios),
            'failures': sum(bool(r[arm]['failure']) for r in part for arm in ('baseline', candidate))}
    # Image-only selector cost, measured on all original camera frames; no text.
    diagnostics = []
    for e in frozen['camera']:
        if e['arm'] == 'baseline':
            pixels = np.asarray(Image.open(frozen['unique_inputs'][e['key']]['path']).convert('RGB'))
            for _ in range(3):
                start = time.perf_counter()
                diagnostic(pixels)
                diagnostics.append((time.perf_counter()-start)*1000)
    for entry in assets.values():
        if sha(entry['path']) != entry['sha256']:
            raise ValueError('assets changed during timing')
    result = {'receipt': receipt, 'summary': summary, 'pairs': rows, 'load_after': os.getloadavg(),
              'selector_per_frame_median_ms': float(np.median(diagnostics)),
              'selector_per_frame_p95_ms': float(np.percentile(diagnostics, 95)),
              'limits': 'Pinned single-core sequential native processes including PNG save/startup. Pixels loaded before timer; decoding excluded equally. Small clustered DEV timing set; not bench/speed_ab, browser, mobile, memory or capture latency.'}
    write(a.output, result)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
