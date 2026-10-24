#!/usr/bin/env python3
"""Freeze before inference; evaluate only explicit existing DEV allowlists.

Never imports data preparation, enumerates source directories, or opens archives.
Private results are immutable per run. No training or restored-text ground truth.
"""
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image
import pypdfium2 as pdfium

from optics import ARMS, CONDITIONS, preprocess, degrade, diagnostic

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PUBLIC = Path('/tmp/docscan-public-data')
ROOT = Path('/tmp/docscan-research-optics')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, obj):
    with Path(path).open('x') as f:
        json.dump(obj, f, indent=2, allow_nan=False)
        f.write('\n')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


score = module('fixed_document_score', REPO/'experiments/public_documents/evaluate.py')
idscore = module('fixed_id_score', REPO/'experiments/public_id/score_id.py')


def load_documents():
    """Recreate the existing manifest using existing renders, never rewrite them."""
    folder = REPO/'experiments/public_documents'
    expected = json.loads((folder/'ocr-dev-v1.json').read_text())
    protocol = json.loads((folder/'protocol.json').read_text())
    if sha(folder/'manifest.json') != expected['source_manifest_sha256']:
        raise ValueError('source manifest changed')
    if sha(folder/'protocol.json') != expected['protocol_sha256']:
        raise ValueError('source protocol changed')
    bank_text = {}
    manifest = json.loads((folder/'manifest.json').read_text())
    bank_hashes = {r['path']: r['sha256'] for r in manifest['bankstatemently']['files']}
    for identity in protocol['bankstatemently']['dev']:
        rel = f'datasets/basic/{identity}/{identity}-statement.pdf'
        path = PUBLIC/'bankstatemently'/rel
        if sha(path) != bank_hashes[rel]:
            raise ValueError('PDF changed')
        with pdfium.PdfDocument(path) as pdf:
            for i in range(len(pdf)):
                bank_text[f'{identity}-p{i+1}'] = pdf[i].get_textpage().get_text_range()
    samples = []
    for row in expected['samples']:
        ident, source = row['id'], row['source']
        if source == 'fatura':
            path = PUBLIC/'fatura/dev'/f'{ident}.jpg'
            truth = PUBLIC/'fatura/dev'/f'{ident}.json'
            if sha(truth) != row['truth_sha256']:
                raise ValueError('invoice truth changed')
            fields = json.loads(truth.read_text())['fields']
            sample = {**row, 'fields': fields, 'group': ident.split('_Instance')[0]}
        elif source == 'bankstatemently':
            path = PUBLIC/'bankstatemently/rendered-dev-v1'/f'{ident}.png'
            text = bank_text[ident]
            if hashlib.sha256(text.encode()).hexdigest() != row['truth_sha256']:
                raise ValueError('bank truth changed')
            sample = {**row, 'text': text, 'group': ident.rsplit('-p', 1)[0]}
        else:
            raise ValueError('unknown source')
        if sha(path) != row['image_sha256']:
            raise ValueError('document image changed')
        samples.append({**sample, 'path': str(path)})
    if len(samples) != 60 or len({s['id'] for s in samples}) != 60:
        raise ValueError('document denominator changed')
    return samples


def load_camera():
    manifest = json.loads((REPO/'experiments/public_id/midv500-dev-v1.json').read_text())
    # Only the already authorized DEV truth and frames, never reserved metadata.
    hashes = {r['path']: r['sha256'] for r in manifest['files']}
    root = PUBLIC/'midv500'
    if sha(root/'dev.json') != hashes['dev.json']:
        raise ValueError('camera truth changed')
    records = json.loads((root/'dev.json').read_text())
    for row in records:
        if row['split'] != 'dev' or not row['frame'].startswith('dev/'):
            raise ValueError('DEV only')
        if sha(root/row['frame']) != hashes[row['frame']]:
            raise ValueError('camera frame changed')
    if len(records) != 18 or len({r['id'] for r in records}) != 18:
        raise ValueError('camera denominator changed')
    return records


def snapshot(run):
    paths = {
        'ocr': Path('/tmp/docscan-research-ocr/native/tiny/reader'),
        'detector': Path('/tmp/docscan-ppocr-v6/tiny_det/inference.onnx'),
        'recognizer': Path('/tmp/docscan-ppocr-v6/tiny_rec/inference.onnx'),
        'scan': Path('/tmp/docscan-research-capture/bin/scan'),
        'text-detection.rten': Path('/tmp/docscan-research-capture/models/text-detection.rten'),
        'text-recognition.rten': Path('/tmp/docscan-research-capture/models/text-recognition.rten'),
    }
    build = json.loads(Path('/tmp/docscan-research-ocr/native/tiny/build.json').read_text())
    if sha(paths['ocr']) != build['binary_sha256']:
        raise ValueError('OCR binary changed')
    if sha(REPO/'docscan/src/text_v6.rs') != build['source_sha256']:
        raise ValueError('probe does not match current OCR source')
    for role in ('detector', 'recognizer'):
        if sha(paths[role]) != build['model_hashes'][role]:
            raise ValueError('OCR model changed')
    prior = json.loads((REPO/'experiments/research_capture/evidence/build-and-decoder-pin.json').read_text())
    # Keep the complete old build receipt; all exact snapshot bytes are pinned anew.
    (run/'assets').mkdir()
    frozen = {}
    for name, path in paths.items():
        before = sha(path)
        dest = run/'assets'/name
        shutil.copy2(path, dest)
        if sha(dest) != before or sha(path) != before:
            raise ValueError('concurrent asset change')
        dest.chmod(0o700 if name in ('ocr', 'scan') else 0o600)
        frozen[name] = {'path': str(dest), 'sha256': before}
    return frozen, {'ocr_build': build, 'capture_build_receipt': prior}


def native(path, engine, assets):
    if engine == 'ocr':
        cmd = [assets['ocr']['path'], assets['detector']['path'], assets['recognizer']['path'], str(path)]
    else:
        cmd = [assets['scan']['path'], '--models='+str(Path(assets['scan']['path']).parent), str(path)]
    start = time.perf_counter()
    failed = None
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                                env={**os.environ, 'RTEN_NUM_THREADS': '1', 'RAYON_NUM_THREADS': '1', 'SCAN_MAX_WIDTH': '1280'})
        if result.returncode:
            raise RuntimeError('native_exit')
        out = json.loads(result.stdout)
        if out.get('error'):
            raise ValueError('native_error')
        if engine == 'ocr' and (not isinstance(out.get('text'), str) or not isinstance(out.get('lines'), list)):
            raise ValueError('invalid_ocr')
        if engine == 'scan' and (not isinstance(out.get('accepted'), bool) or out.get('model_directory') != str(Path(assets['scan']['path']).parent)):
            raise ValueError('invalid_scan')
    except (subprocess.TimeoutExpired, RuntimeError, ValueError, OSError) as exc:
        failed = type(exc).__name__
        out = {'text': '', 'lines': [], 'accepted': False}
    return {'output': out, 'failure': failed, 'native_ms': (time.perf_counter()-start)*1000}


def fields_for(sample, prediction):
    if sample['source'] == 'bankstatemently':
        return [score.token_score(sample['text'], prediction.get('text', ''))]
    return [score.token_score(f['text'], score.region_text(prediction.get('lines', []), f['bbox'])) for f in sample['fields']]


def aggregate(entries, samples, outputs):
    groups = defaultdict(list)
    meta = defaultdict(lambda: {'pages': 0, 'failures': 0, 'empty_readings': 0, 'transformed': 0,
                                 'exact_regions_gained': 0, 'exact_regions_lost': 0,
                                 'pages_token_gain': 0, 'pages_token_loss': 0})
    baseline = {(e['index'], e['condition']): e for e in entries if e['arm'] == 'baseline'}
    for e in entries:
        s = samples[e['index']]
        key = '/'.join((s['source'], e['condition'], e['arm']))
        pred = outputs[e['key']]
        fields = fields_for(s, pred['output'])
        base = fields_for(s, outputs[baseline[e['index'], e['condition']]['key']]['output'])
        groups[key].extend(fields)
        m = meta[key]
        m['pages'] += 1
        m['failures'] += bool(pred['failure'])
        m['empty_readings'] += not bool(score.normal(pred['output'].get('text', '')))
        m['transformed'] += e['preprocess']['changed']
        m['exact_regions_gained'] += sum(not a['exact'] and b['exact'] for a, b in zip(base, fields))
        m['exact_regions_lost'] += sum(a['exact'] and not b['exact'] for a, b in zip(base, fields))
        delta = sum(f['matched_tokens'] for f in fields)-sum(f['matched_tokens'] for f in base)
        m['pages_token_gain'] += delta > 0
        m['pages_token_loss'] += delta < 0
    return {k: {**score.summary(v), **meta[k]} for k, v in groups.items()}


def camera_results(entries, records, outputs):
    scored = {}
    for arm in ARMS:
        rows = [e for e in entries if e['arm'] == arm]
        items = [{'id': records[e['index']]['id'], 'output': outputs[e['key']]['output']} for e in rows]
        result = idscore.score({'items': items, 'input': 'raw-camera'}, records)
        write(camera_results.run/f'camera-{arm}-private.json', result)
        scored[arm] = result
    base = scored['baseline']['items']
    summaries = {}
    for arm, result in scored.items():
        rows = [e for e in entries if e['arm'] == arm]
        summaries[arm] = {**result['summary'],
            'failures': sum(bool(outputs[e['key']]['failure']) for e in rows),
            'abstentions': sum(not o['accepted'] for o in result['items']),
            'transformed': sum(e['preprocess']['changed'] for e in rows),
            'new_wrong_accepts': sum(not a['accepted_wrong'] and b['accepted_wrong'] for a, b in zip(base, result['items'])),
            'correct_accepts_lost': sum(a['accepted_correct'] and not b['accepted_correct'] for a, b in zip(base, result['items']))}
    return summaries


def bursts(doc_entries, cam_entries, samples, records, outputs):
    doc_baseline = {(e['index'], e['condition']): e for e in doc_entries if e['arm'] == 'baseline'}
    groups = defaultdict(list)
    detail = []
    for i, sample in enumerate(samples):
        conditions = ['dark', 'glare', 'motion_blur']
        offset = int(hashlib.sha256(sample['id'].encode()).hexdigest()[:8], 16) % 3
        conditions = conditions[offset:]+conditions[:offset]
        choices = [doc_baseline[i, c] for c in conditions]
        chosen = max(choices, key=lambda e: e['diagnostic']['selection_score'])
        for arm, e in [('first', choices[0]), ('selected', chosen)]:
            groups[sample['source']+'/'+arm].extend(fields_for(sample, outputs[e['key']]['output']))
        detail.append({'index': i, 'first': choices[0]['key'], 'selected': chosen['key'],
                       'selected_condition': chosen['condition'], 'failed': bool(outputs[chosen['key']]['failure'])})
    camera_groups = defaultdict(list)
    for e in cam_entries:
        if e['arm'] == 'baseline':
            record = records[e['index']]
            camera_groups[record['layout']+'/'+record['condition']].append(e)
    camera = {}
    for arm in ('first', 'selected'):
        items, truth = [], []
        for choices in camera_groups.values():
            e = choices[0] if arm == 'first' else max(choices, key=lambda x: x['diagnostic']['selection_score'])
            record = records[e['index']]
            truth.append(record)
            items.append({'id': record['id'], 'output': outputs[e['key']]['output']})
        result = idscore.score({'items': items, 'input': 'raw-camera-burst'}, truth)
        camera[arm] = {**result['summary'], 'abstentions': sum(not i['accepted'] for i in result['items'])}
        write(bursts.run/f'burst-camera-{arm}-private.json', result)
    write(bursts.run/'burst-document-private.json', detail)
    return {'document': {k: score.summary(v) for k, v in groups.items()}, 'camera': camera,
            'document_bursts': len(samples), 'camera_bursts': len(camera_groups),
            'selected_failures': sum(d['failed'] for d in detail),
            'selected_conditions': {c: sum(d['selected_condition'] == c for d in detail) for c in ('dark', 'glare', 'motion_blur')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE/'results-v1.json')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('refusing to overwrite report')
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, exist_ok=True)
    ROOT.chmod(0o700)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=ROOT))
    for name in ('inputs', 'predictions'):
        (run/name).mkdir()
    camera_results.run = run
    bursts.run = run
    samples, records = load_documents(), load_camera()
    assets, build = snapshot(run)
    unique, documents, camera, negatives = {}, [], [], []

    def register(rgb, engine, row):
        key = engine+'-'+hashlib.sha256(rgb.shape.__repr__().encode()+rgb.tobytes()).hexdigest()
        if key not in unique:
            path = run/'inputs'/f'{key}.png'
            Image.fromarray(rgb).save(path)
            unique[key] = {'path': str(path), 'engine': engine, 'sha256': sha(path)}
        return {**row, 'key': key}

    for i, sample in enumerate(samples):
        original = np.asarray(Image.open(sample['path']).convert('RGB'))
        seed = int(hashlib.sha256(sample['id'].encode()).hexdigest()[:8], 16)
        for condition in CONDITIONS:
            pixels = degrade(original, condition, seed)
            diag = diagnostic(pixels)
            for arm in ARMS:
                start = time.perf_counter()
                result, meta = preprocess(pixels, arm)
                documents.append(register(result, 'ocr', {'index': i, 'condition': condition, 'arm': arm,
                    'preprocess': meta, 'preprocess_ms': (time.perf_counter()-start)*1000, 'diagnostic': diag}))
    for i, record in enumerate(records):
        pixels = np.asarray(Image.open(PUBLIC/'midv500'/record['frame']).convert('RGB'))
        diag = diagnostic(pixels)
        for arm in ARMS:
            start = time.perf_counter()
            result, meta = preprocess(pixels, arm)
            camera.append(register(result, 'scan', {'index': i, 'arm': arm, 'preprocess': meta,
                'preprocess_ms': (time.perf_counter()-start)*1000, 'diagnostic': diag}))
    # Non-text synthetic controls are fixed, with no real portrait or handwriting.
    for i in range(6):
        y, x = np.mgrid[:640, :480]
        gray = [np.full((640, 480), 255), np.full((640, 480), 50),
                35+200*x/479, 220+20*np.sin(x/40),
                np.clip(120+np.random.default_rng(71).normal(0, 12, (640, 480)), 0, 255),
                255-120*np.exp(-((x-240)**2+(y-320)**2)/20000)][i]
        pixels = np.repeat(gray.astype(np.uint8)[..., None], 3, axis=2)
        for arm in ARMS:
            result, meta = preprocess(pixels, arm)
            negatives.append(register(result, 'ocr', {'index': i, 'arm': arm, 'preprocess': meta}))
    source_paths = [HERE/'run.py', HERE/'optics.py', HERE/'protocol.json', Path(score.__file__), Path(idscore.__file__),
                    REPO/'experiments/public_documents/ocr-dev-v1.json', REPO/'experiments/public_id/midv500-dev-v1.json']
    freeze = {'frozen_utc': datetime.now(timezone.utc).isoformat(), 'protocol': json.loads((HERE/'protocol.json').read_text()),
        'source_hashes': {str(p.relative_to(REPO)): sha(p) for p in source_paths}, 'assets': assets, 'build': build,
        'packages': {n: importlib.metadata.version(n) for n in ('numpy', 'pillow', 'opencv-python-headless', 'pypdfium2')},
        'effective_train': [], 'dev_groups': sorted({s['source']+'/'+s['group'] for s in samples})+
            sorted({r['layout']+'/all-Apple-device-sessions' for r in records}),
        'documents': documents, 'camera': camera, 'negatives': negatives, 'unique_inputs': unique}
    write(run/'freeze.json', freeze)
    print(json.dumps({'private_run': str(run), 'frozen': freeze['frozen_utc'], 'inferences': len(unique)}), flush=True)
    start = time.monotonic()

    def execute(item):
        key, entry = item
        if sha(entry['path']) != entry['sha256']:
            raise ValueError('frozen input changed')
        out = native(entry['path'], entry['engine'], assets)
        write(run/'predictions'/f'{key}.json', out)
        return key, out

    outputs = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for key, out in pool.map(execute, unique.items()):
            outputs[key] = out
            if len(outputs) % 25 == 0:
                print(json.dumps({'completed': len(outputs), 'total': len(unique)}), flush=True)
    for name, entry in assets.items():
        if sha(entry['path']) != entry['sha256']:
            raise ValueError('frozen artifact changed')
    if any(sha(REPO/p) != h for p, h in freeze['source_hashes'].items()):
        raise ValueError('source changed during inference')
    report = {'version': 'optics-dev-v1', 'completed_utc': datetime.now(timezone.utc).isoformat(),
        'freeze_sha256': sha(run/'freeze.json'), 'private_run': str(run),
        'source_hashes': freeze['source_hashes'], 'asset_hashes': {k: v['sha256'] for k, v in assets.items()},
        'frozen_utc': freeze['frozen_utc'], 'packages': freeze['packages'],
        'effective_train_count': 0, 'dev_document_groups': 8, 'dev_camera_specimens': 3,
        'documents': aggregate(documents, samples, outputs), 'camera': camera_results(camera, records, outputs),
        'bursts': bursts(documents, camera, samples, records, outputs),
        'negatives': {arm: {'pages': 6, 'with_text': sum(bool(score.normal(outputs[e['key']]['output'].get('text', ''))) for e in negatives if e['arm'] == arm),
                           'failures': sum(bool(outputs[e['key']]['failure']) for e in negatives if e['arm'] == arm)} for arm in ARMS},
        'unique_inferences': len(outputs), 'inference_failures': sum(bool(o['failure']) for o in outputs.values()),
        'accuracy_wall_seconds_descriptive': time.monotonic()-start,
        'glare_diagnostic': {c: {'pages': 60, 'flagged': sum(e['diagnostic']['glare_suspect_fraction'] > 0 for e in documents if e['condition'] == c and e['arm'] == 'baseline')}
                             for c in CONDITIONS},
        'raw_hashes': {key: sha(run/'predictions'/f'{key}.json') for key in outputs}}
    # Clean baseline must exactly reproduce every previously scored page/region.
    historical = json.loads((REPO/'experiments/research_ocr/results/native-tiny-tiny-standard.json').read_text())
    clean = {samples[e['index']]['id']: fields_for(samples[e['index']], outputs[e['key']]['output'])
             for e in documents if e['condition'] == 'clean' and e['arm'] == 'baseline'}
    report['historical_baseline_exact_parity'] = all(
        clean[r['id']] == [{k: v for k, v in f.items() if k != 'label'} for f in r['scores']] for r in historical['rows'])
    write(args.output, report)
    print(json.dumps({k: report[k] for k in ('inference_failures', 'historical_baseline_exact_parity', 'camera', 'bursts')}), flush=True)


if __name__ == '__main__':
    main()
