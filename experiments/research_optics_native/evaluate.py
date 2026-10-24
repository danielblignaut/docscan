#!/usr/bin/env python3
"""Native (Rust) global exposure against the frozen Python arm and baseline.

Reuses only the frozen optics DEV run (`experiments/research_optics/results-v1.json`
and its private `freeze.json`): the same authorized DEV inputs, the same frozen
OCR/scan binaries and models, the same scorers and every truth denominator.
No data is fetched, prepared or enumerated; no threshold, gate or score changes.

For every frozen baseline input (300 document pages x conditions, 18 camera
frames, 6 non-text controls) it runs the Rust binary and the frozen Python arm,
records pixel/gate/gain parity, freezes every native output, then runs FRESH
native inference on every native output the gate changed. An untouched output is
the baseline's bytes by construction and reuses the frozen baseline prediction.
The public report holds counts and opaque specimen ids only, never OCR text.
"""
from collections import defaultdict
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OPTICS = REPO/'experiments/research_optics'
sys.path.insert(0, str(OPTICS))
from optics import preprocess  # noqa: E402
from run import sha, write, load_documents, load_camera, native, fields_for, aggregate, score, idscore  # noqa: E402

ROOT = Path('/tmp/docscan-research-optics-native')


def key_of(engine, rgb):
    return engine+'-'+hashlib.sha256(rgb.shape.__repr__().encode()+rgb.tobytes()).hexdigest()


def rust(binary, rgb, work):
    h, w = rgb.shape[:2]
    src, dst = work/'in.raw', work/'out.raw'
    dst.unlink(missing_ok=True)
    src.write_bytes(np.uint32(w).tobytes()+np.uint32(h).tobytes()+rgb.tobytes())
    result = subprocess.run([binary, 'apply', str(src), str(dst)], capture_output=True, text=True, timeout=60, check=True)
    meta = json.loads(result.stdout)
    if meta['applied']:
        data = dst.read_bytes()
        assert int.from_bytes(data[:4], 'little') == w and int.from_bytes(data[4:8], 'little') == h
        out = np.frombuffer(data[8:], np.uint8).reshape(h, w, 3)
    else:
        assert not dst.exists()
        out = rgb
    return out, meta


def parity(rgb, ref, ref_meta, out, meta):
    diff = np.abs(out.astype(np.int16)-ref.astype(np.int16))
    p90 = ref_meta.get('background_p90')
    return {'python_applied': bool(p90 is not None and p90 < .55), 'native_applied': meta['applied'],
            'python_p90': p90, 'native_p90': meta['background_p90'],
            'p90_abs_diff': abs(meta['background_p90']-p90),
            'native_gain': meta['gain'],
            'python_gain': min(4., .85/max(p90, .01)) if p90 < .55 else 1.0,
            'pixel_identical_to_python': bool(np.array_equal(out, ref)),
            'bytes_differing_from_python': int(np.count_nonzero(diff)), 'max_abs_diff_from_python': int(diff.max()),
            'native_changed': bool(not np.array_equal(out, rgb)), 'python_changed': bool(ref_meta['changed']),
            'native_analyse_ms_descriptive': meta['analyse_ns']/1e6, 'native_apply_ms_descriptive': meta['apply_ns']/1e6}


def camera_summary(rows, records, outputs, run, name):
    items = [{'id': records[e['index']]['id'], 'output': outputs[e['key']]['output']} for e in rows]
    result = idscore.score({'items': items, 'input': 'raw-camera'}, records)
    write(run/f'camera-{name}-private.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--results', type=Path, default=OPTICS/'results-v1.json')
    p.add_argument('--output', type=Path, default=HERE/'results-native-v1.json')
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('refusing to overwrite report')
    os.umask(0o077)
    report = json.loads(args.results.read_text())
    frozen_run = Path(report['private_run'])
    if sha(frozen_run/'freeze.json') != report['freeze_sha256']:
        raise ValueError('frozen run changed')
    frozen = json.loads((frozen_run/'freeze.json').read_text())
    for path, digest in frozen['source_hashes'].items():
        if sha(REPO/path) != digest:
            raise ValueError(f'reference source changed: {path}')
    assets = frozen['assets']
    for entry in assets.values():
        if sha(entry['path']) != entry['sha256']:
            raise ValueError('frozen assets changed')
    samples, records = load_documents(), load_camera()

    ROOT.mkdir(mode=0o700, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=ROOT))
    for name in ('inputs', 'predictions', 'work'):
        (run/name).mkdir()
    binary = run/'exposure'
    shutil.copy2(args.binary, binary)
    binary.chmod(0o700)
    native_sources = {str(p.relative_to(REPO)): sha(p) for p in
                      (REPO/'docscan/src/exposure.rs', HERE/'src/main.rs', HERE/'Cargo.toml', Path(__file__))}

    def frozen_prediction(k):
        path = frozen_run/'predictions'/f'{k}.json'
        if sha(path) != report['raw_hashes'][k]:
            raise ValueError('frozen prediction changed')
        return json.loads(path.read_text())

    groups = {'documents': {}, 'camera': {}, 'negatives': {}}
    for group in groups:
        for e in frozen[group]:
            ident = (e['index'], e.get('condition'))
            groups[group].setdefault(ident, {})[e['arm']] = e
    unique, rows = {}, {g: [] for g in groups}
    for group, pairs in groups.items():
        engine = 'scan' if group == 'camera' else 'ocr'
        for (index, condition), arms in sorted(pairs.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
            base = arms['baseline']
            entry = frozen['unique_inputs'][base['key']]
            if sha(entry['path']) != entry['sha256']:
                raise ValueError('frozen input changed')
            rgb = np.asarray(Image.open(entry['path']).convert('RGB'))
            if key_of(engine, rgb) != base['key']:
                raise ValueError('frozen baseline does not reproduce')
            ref, ref_meta = preprocess(rgb, 'global_exposure')
            if key_of(engine, ref) != arms['global_exposure']['key']:
                raise ValueError('frozen Python arm does not reproduce')
            out, meta = rust(str(binary), rgb, run/'work')
            k = key_of(engine, out)
            if k != base['key'] and k not in unique:
                path = run/'inputs'/f'{k}.png'
                Image.fromarray(out).save(path)
                unique[k] = {'path': str(path), 'engine': engine, 'sha256': sha(path)}
            rows[group].append({'index': index, 'condition': condition, 'baseline_key': base['key'],
                                'python_key': arms['global_exposure']['key'], 'native_key': k,
                                **parity(rgb, ref, ref_meta, out, meta)})
    freeze = {'frozen_utc': datetime.now(timezone.utc).isoformat(), 'reference_results_sha256': sha(args.results),
              'reference_freeze_sha256': report['freeze_sha256'], 'binary_sha256': sha(binary),
              'native_sources': native_sources, 'rows': rows, 'unique_native_inputs': unique}
    write(run/'freeze.json', freeze)
    print(json.dumps({'private_run': str(run), 'fresh_inferences': len(unique)}), flush=True)

    def execute(item):
        k, entry = item
        if sha(entry['path']) != entry['sha256']:
            raise ValueError('frozen native input changed')
        out = native(entry['path'], entry['engine'], assets)
        write(run/'predictions'/f'{k}.json', out)
        return k, out

    outputs = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for k, out in pool.map(execute, unique.items()):
            outputs[k] = out
    for group in rows.values():
        for r in group:
            for k in (r['baseline_key'], r['python_key']):
                if k not in outputs:
                    outputs.setdefault(k, frozen_prediction(k))
    # Python-arm predictions are frozen; fresh native ones must not overwrite them.
    fresh = {k: outputs[k] for k in unique}
    python_outputs = {r['python_key']: frozen_prediction(r['python_key']) for g in rows.values() for r in g}
    if sha(binary) != freeze['binary_sha256'] or any(sha(e['path']) != e['sha256'] for e in assets.values()):
        raise ValueError('binary or assets changed during inference')

    # Documents: score native beside the frozen baseline with the unchanged aggregate().
    doc_entries = []
    for r in rows['documents']:
        doc_entries.append({'index': r['index'], 'condition': r['condition'], 'arm': 'baseline',
                            'key': r['baseline_key'], 'preprocess': {'changed': False}})
        doc_entries.append({'index': r['index'], 'condition': r['condition'], 'arm': 'native_global_exposure',
                            'key': r['native_key'], 'preprocess': {'changed': r['native_changed']}})
    documents = aggregate(doc_entries, samples, outputs)

    # Per-page dark comparison: native vs baseline, and native vs frozen Python arm.
    dark = []
    for r in rows['documents']:
        if r['condition'] != 'dark':
            continue
        s = samples[r['index']]
        base, nat = (fields_for(s, outputs[r[k]]['output']) for k in ('baseline_key', 'native_key'))
        py = fields_for(s, python_outputs[r['python_key']]['output'])
        b, n = score.summary(base), score.summary(nat)
        dark.append({'sample_id': s['id'], 'source': s['source'],
                     'exact_regions_lost': sum(x['exact'] and not y['exact'] for x, y in zip(base, nat)),
                     'exact_regions_gained': sum(not x['exact'] and y['exact'] for x, y in zip(base, nat)),
                     'matched_token_delta': n['matched_tokens']-b['matched_tokens'],
                     'unmatched_prediction_delta': (n['predicted_tokens']-n['matched_tokens'])-(b['predicted_tokens']-b['matched_tokens']),
                     'pixel_identical_to_python': r['pixel_identical_to_python'],
                     'scores_identical_to_python_arm': nat == py,
                     'reading_identical_to_frozen_python_arm': outputs[r['native_key']]['output'].get('text') == python_outputs[r['python_key']]['output'].get('text'),
                     'native_failure': bool(outputs[r['native_key']]['failure'])})
    dark_counts = {src: {'pages': sum(d['source'] == src for d in dark),
                         'lost_any_exact_region_pages': sum(d['exact_regions_lost'] > 0 for d in dark if d['source'] == src),
                         'exact_regions_lost': sum(d['exact_regions_lost'] for d in dark if d['source'] == src),
                         'exact_regions_gained': sum(d['exact_regions_gained'] for d in dark if d['source'] == src),
                         'lost_matched_token_pages': sum(d['matched_token_delta'] < 0 for d in dark if d['source'] == src),
                         'more_unmatched_prediction_pages': sum(d['unmatched_prediction_delta'] > 0 for d in dark if d['source'] == src),
                         'pages_scores_identical_to_python_arm': sum(d['scores_identical_to_python_arm'] for d in dark if d['source'] == src),
                         'pages_reading_identical_to_frozen_python_arm': sum(d['reading_identical_to_frozen_python_arm'] for d in dark if d['source'] == src)}
                   for src in ('fatura', 'bankstatemently')}

    # Camera: same scorer, same 18 frames; new wrong accepts against baseline.
    cam = sorted(rows['camera'], key=lambda r: r['index'])
    scored = {name: camera_summary([{'index': r['index'], 'key': r[k]} for r in cam], records, outputs, run, name)
              for name, k in (('baseline', 'baseline_key'), ('native_global_exposure', 'native_key'))}
    base_items = scored['baseline']['items']
    camera = {name: {**res['summary'], 'abstentions': sum(not o['accepted'] for o in res['items']),
                     'failures': sum(bool(outputs[r[k]]['failure']) for r in cam),
                     'transformed': sum(r['native_changed'] for r in cam) if name != 'baseline' else 0,
                     'new_wrong_accepts': sum(not a['accepted_wrong'] and b['accepted_wrong'] for a, b in zip(base_items, res['items'])),
                     'correct_accepts_lost': sum(a['accepted_correct'] and not b['accepted_correct'] for a, b in zip(base_items, res['items']))}
              for (name, res), k in zip(scored.items(), ('baseline_key', 'native_key'))}

    negatives = {name: {'pages': len(rows['negatives']),
                        'with_text': sum(bool(score.normal(outputs[r[k]]['output'].get('text', ''))) for r in rows['negatives']),
                        'failures': sum(bool(outputs[r[k]]['failure']) for r in rows['negatives']),
                        'transformed': sum(r['native_changed'] for r in rows['negatives']) if name != 'baseline' else 0}
                 for name, k in (('baseline', 'baseline_key'), ('native_global_exposure', 'native_key'))}

    every = [r for g in rows.values() for r in g]
    parity_summary = {
        'inputs': len(every),
        'gate_agreement': sum(r['python_applied'] == r['native_applied'] for r in every),
        'changed_agreement': sum(r['python_changed'] == r['native_changed'] for r in every),
        'pixel_identical_to_python': sum(r['pixel_identical_to_python'] for r in every),
        'max_abs_pixel_diff': max(r['max_abs_diff_from_python'] for r in every),
        'bytes_differing_total': sum(r['bytes_differing_from_python'] for r in every),
        'max_p90_abs_diff': max(r['p90_abs_diff'] for r in every),
        'max_gain_rel_diff': max(abs(r['native_gain']-r['python_gain'])/r['python_gain'] for r in every),
        'min_gate_margin': min(abs(r['python_p90']-.55) for r in every),
        'applied': sum(r['native_applied'] for r in every)}
    public_rows = {g: [{k: v for k, v in r.items() if not k.endswith('_key')} for r in rs] for g, rs in rows.items()}
    result = {'version': 'native-global-exposure-dev-v1', 'completed_utc': datetime.now(timezone.utc).isoformat(),
              'private_run': str(run), 'freeze_sha256': sha(run/'freeze.json'),
              'reference_results_sha256': sha(args.results), 'reference_freeze_sha256': report['freeze_sha256'],
              'binary_sha256': freeze['binary_sha256'], 'native_sources': native_sources,
              'fresh_inferences': len(fresh), 'fresh_inference_failures': sum(bool(o['failure']) for o in fresh.values()),
              'parity': parity_summary, 'documents': documents, 'frozen_python_documents': report['documents'],
              'dark_paired': dark_counts, 'dark_pages': dark, 'camera': camera, 'frozen_python_camera': report['camera'],
              'negatives': negatives, 'parity_rows': public_rows,
              'raw_hashes': {k: sha(run/'predictions'/f'{k}.json') for k in fresh},
              'limits': 'Same 60 DEV pages (3 statements, 5 invoice layouts) and 18 camera frames as the frozen run; '
                        'native x86-64 release build only, no WASM/browser/phone; procedural degradations; '
                        'no significance claim beyond the frozen review; utility candidate, not acceptance.'}
    write(args.output, result)
    print(json.dumps({'parity': parity_summary, 'dark_paired': dark_counts, 'camera': camera['native_global_exposure'],
                      'negatives': negatives}), flush=True)


if __name__ == '__main__':
    main()
