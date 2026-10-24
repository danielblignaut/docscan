#!/usr/bin/env python3
"""Freeze -> prepare -> train/calibrate -> evaluate every arm on unchanged DEV.

All raw pixels, per-item scores, identities, model weights and receipts remain in
an exclusive owner-private directory outside git. Only aggregate reports and
code/protocol hashes may be published. Use a new directory for every attempt.
"""
from __future__ import annotations
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time
import cv2
import numpy as np
from PIL import Image
from detector import VERSION, FEATURES, extract, indices, score, decide
from synthetic import render

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LABELS = ('bona_fide_capture', 'screen_recapture', 'print_copy')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, obj):
    with Path(path).open('x') as f:
        json.dump(obj, f, indent=2, allow_nan=False)
        f.write('\n')


def source_hashes():
    return {name: digest(HERE/name) for name in ('detector.py','synthetic.py','study.py','real_study.py','receipts.py','fetch_dlc.py','fetch_train_only.py')} | {n:digest(HERE/n) for n in ('protocol.json','source-notices.json','author-crop-notice.json')}


def private_dir(path):
    path = path.resolve()
    if path.is_relative_to(REPO):
        raise ValueError('artifacts must be outside git')
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(path, 0o700)
    return path


def safe_path(root, name):
    path = (root/name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('path escapes data root')
    return path


def validate_records(records):
    """Audit before any image read: allowed split names, group/device isolation."""
    ids = set()
    seen = {name: {} for name in ('identity', 'specimen', 'device')}
    hashes = {}
    for r in records:
        if r['split'] not in ('train', 'calibration', 'dev', 'real_dev') or r['label'] not in LABELS:
            raise ValueError('unsupported split/label')
        if r['id'] in ids:
            raise ValueError('duplicate item')
        ids.add(r['id'])
        for key, owners in seen.items():
            group = r[key]
            if not group or group in owners and owners[group] != r['split']:
                raise ValueError('group leakage: '+key)
            owners[group] = r['split']
        if 'sha256' in r:
            prior = hashes.setdefault(r['sha256'], r['split'])
            if prior != r['split']:
                raise ValueError('duplicate image across splits')
    return True


def prepare(root, config):
    # Fix all identities, synthetic device assignments, conditions and external
    # filenames BEFORE rendering or inference. No discovery/listing of media.
    planned = []
    specimen = 0
    for split, count in config['groups'].items():
        for group in range(count):
            device = config['devices'][split][group % len(config['devices'][split])]
            for condition in config['negative_conditions']+config['attack_conditions']:
                label = 'screen_recapture' if condition.startswith('screen') else 'print_copy' if condition.startswith('print') else 'bona_fide_capture'
                planned.append(dict(id=f'syn-{specimen:04}-{condition}', identity=f'syn-{specimen}',
                                    specimen=f'syn-{specimen}', device=f'simulator-{device}',
                                    split=split, condition=condition, label=label, seed_specimen=specimen,
                                    seed_device=device, path=f'images/{specimen:04}-{condition}.png'))
            specimen += 1
    spec = config['real_dev']
    real_root = Path(spec['root'])
    # Read only the already-pinned DEV manifest and explicit allowlisted files.
    original_manifest = json.loads((real_root/'manifest.json').read_text())
    if sorted(original_manifest['dev_layouts']) != sorted(spec['layouts']):
        raise ValueError('unexpected existing DEV manifest')
    pins = {e['path']: e for e in original_manifest['files']}
    for layout in spec['layouts']:
        for condition in spec['conditions']:
            for frame in spec['frames']:
                stem = condition+layout[:2]+'_'+frame
                media = 'dev/'+layout+'/'+stem+'_frame.png'
                annotation = 'raw/'+layout+'/'+stem+'.json'
                for rel in (media, annotation):
                    if rel not in pins:
                        raise ValueError('missing pinned DEV item')
                planned.append(dict(id='real-'+stem, identity='midv-'+layout, specimen='midv-'+layout,
                                    device='midv-apple-capture', split='real_dev', condition=condition,
                                    label='bona_fide_capture', path=str(real_root/media),
                                    sha256=pins[media]['sha256'], annotation=str(real_root/annotation),
                                    annotation_sha256=pins[annotation]['sha256']))
    if sum(r['split']=='real_dev' for r in planned) != spec['count']:
        raise ValueError('real denominator changed')
    validate_records(planned)
    write(root/'plan.json', planned)
    (root/'images').mkdir(mode=0o700)
    for row in planned:
        if row['split'] == 'real_dev':
            if digest(row['path']) != row['sha256'] or digest(row['annotation']) != row['annotation_sha256']:
                raise ValueError('existing DEV bytes changed')
            row['quad'] = json.loads(Path(row['annotation']).read_text())['quad']
        else:
            rgb, quad = render(config['seed'], row['seed_specimen'], row['seed_device'], row['condition'], config['synthetic_size'])
            path = safe_path(root, row['path'])
            Image.fromarray(rgb).save(path)
            row.update(sha256=digest(path), quad=quad)
    validate_records(planned)
    write(root/'manifest.json', {'protocol': config['id'], 'records': planned})
    return planned


def features(root, records):
    rows = []
    for index, r in enumerate(records):
        start = time.monotonic()
        try:
            p = Path(r['path']) if r['split'] == 'real_dev' else safe_path(root, r['path'])
            if digest(p) != r['sha256']:
                raise ValueError('input changed')
            with Image.open(p) as im:
                if 'A' in im.getbands() and np.any(np.asarray(im.getchannel('A')) != 255):
                    raise ValueError('nonopaque input')
                rgb = np.asarray(im.convert('RGB'))
            # Global models remain measurable when context/annotation fails.
            global_values = extract(rgb)
            try:
                context_values = extract(rgb, r['quad'])
                context_error = None
            except (ValueError, cv2.error) as exc:
                context_values = None
                context_error = type(exc).__name__+': '+str(exc)
            rows.append(dict(id=r['id'], global_features=global_values.tolist(),
                             context_features=context_values.tolist() if context_values is not None else None,
                             error=None, context_error=context_error, seconds=time.monotonic()-start))
        except (ValueError, OSError, cv2.error) as exc:
            rows.append(dict(id=r['id'], global_features=None, context_features=None,
                             error=type(exc).__name__+': '+str(exc), seconds=time.monotonic()-start))
        if (index+1) % 200 == 0:
            print(f'features {index+1}/{len(records)}', flush=True)
    write(root/'features.json', rows)
    return rows


def fit_logistic(x, y, config):
    mean = x.mean(axis=0); scale = np.maximum(x.std(axis=0), 1e-6)
    z = (x-mean)/scale
    weights = np.zeros(x.shape[1]); bias = 0.
    # Balanced classes; deterministic full-batch gradient descent, L2 weights.
    sample_weights = np.where(y == 1, .5/max(y.mean(), 1e-12), .5/max(1-y.mean(), 1e-12))
    for _ in range(config['iterations']):
        logits = np.clip(z @ weights+bias, -40, 40)
        error = (1/(1+np.exp(-logits))-y)*sample_weights
        weights -= config['learning_rate']*(z.T @ error/len(y)+config['l2']*weights)
        bias -= config['learning_rate']*error.mean()
    return weights, bias, mean, scale


def train(config, records, rows, candidate):
    field = 'context_features' if candidate in ('boundary_context', 'native_patch_texture') else 'global_features'
    ids = indices(candidate)
    fit_rows = [(r, f[field]) for r, f in zip(records, rows) if r['split']=='train']
    # A training failure aborts fitting; do not silently remove hard examples.
    if any(v is None for _, v in fit_rows):
        raise ValueError('training feature failure')
    x = np.array([v for _, v in fit_rows])[:, ids]
    weights, biases = [], []
    for label in LABELS[1:]:
        y = np.array([r['label']==label for r, _ in fit_rows], np.float64)
        weight, bias, mean, scale = fit_logistic(x, y, config['logistic'])
        if y.sum() == 0:
            weight = np.zeros_like(weight); bias = -40.0
        weights.append(weight.tolist()); biases.append(bias)
    model = dict(schema=1, candidate=candidate, feature_version=VERSION, feature_names=FEATURES,
                 indices=ids, mean=mean.tolist(), scale=scale.tolist(), weights=weights, bias=biases,
                 scope='procedural_synthetic_optics_only', deployment_validated=False,
                 confidence_calibrated=False, training_data_license='original_procedural_graphics_no_external_assets',
                 weights_license='research_artifact_no_third_party_weights', thresholds=[])
    cal = [(r, f[field]) for r, f in zip(records, rows) if r['split']=='calibration' and r['label']==LABELS[0]]
    if any(v is None for _, v in cal):
        raise ValueError('calibration failure; cannot silently drop negative')
    scores = np.array([score(model, np.array(v)) for _, v in cal])
    # Strict > max gives zero calibration false warnings; this is an operating
    # threshold, NOT calibrated posterior probability or independent validation.
    model['thresholds'] = np.maximum(scores.max(axis=0), config['decision']['minimum_logit']).tolist()
    model['calibration_groups'] = len({r['specimen'] for r, _ in cal})
    model['calibration_negative_items'] = len(cal)
    return model


def metrics(records, predictions):
    if len(records) != len(predictions) or [r['id'] for r in records] != [p['id'] for p in predictions]:
        raise ValueError('fixed denominator mismatch')
    pos = [i for i, r in enumerate(records) if r['label'] != LABELS[0]]
    neg = [i for i, r in enumerate(records) if r['label'] == LABELS[0]]
    flags = [p['status']=='copy_indicated' for p in predictions]
    groups = {r['specimen'] for r in records if r['label']==LABELS[0]}
    bad_groups = {r['specimen'] for r, flag in zip(records, flags) if flag and r['label']==LABELS[0]}
    n = len(groups)
    # Exact one-sided 95% binomial upper bound only when zero errors; groups
    # share simulated devices, so this is descriptive, not a deployment guarantee.
    bound = 1-.05**(1/n) if n and not bad_groups else None
    conditions = {}
    for condition in sorted({r['condition'] for r in records}):
        ix = [i for i, r in enumerate(records) if r['condition']==condition]
        conditions[condition] = dict(n=len(ix), flags=sum(flags[i] for i in ix),
                                     failures=sum(predictions[i].get('failure', False) for i in ix))
    return dict(items=len(records), attack_items=len(pos), negative_items=len(neg),
                detected_attacks=sum(flags[i] for i in pos), missed_or_abstained_attacks=sum(not flags[i] for i in pos),
                false_positives=sum(flags[i] for i in neg), negative_groups=n, false_positive_groups=len(bad_groups),
                zero_error_group_upper95=bound, abstentions=sum(not v for v in flags),
                failures=sum(p.get('failure', False) for p in predictions), original_verdicts=0,
                gains_vs_constant_unknown=sum(flags[i] for i in pos), regressions_vs_constant_unknown=sum(flags[i] for i in neg),
                by_condition=conditions)


def evaluate(model, records, rows, split):
    selected, predictions = [], []
    for r, f in zip(records, rows):
        if r['split'] != split:
            continue
        selected.append(r)
        if model is None:
            p = dict(status='unknown', is_copy=None, confidence=None, reason='constant_unknown')
        else:
            field = 'context_features' if model['candidate'] in ('boundary_context', 'native_patch_texture') else 'global_features'
            if f[field] is None:
                p = dict(status='unknown', is_copy=None, confidence=None, reason='feature_failure', failure=True)
            else:
                p = decide(model, score(model, np.array(f[field])), allow_experimental=True)
        predictions.append(dict(id=r['id'], **p))
    return metrics(selected, predictions), predictions


def cohort_counts(records):
    result={}
    for split in ('train','calibration','dev'):
        result[split]={}
        for label in LABELS[:2]:
            rows=[r for r in records if r['split']==split and r['label']==label]
            result[split][label]=dict(frames=len(rows),specimens=len({r['specimen'] for r in rows}),
                identities=len({r['identity_group'] for r in rows}),
                clips=len({(r['source'],r['type'],r['clip']) for r in rows}))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--protocol', type=Path, default=HERE/'protocol.json')
    args = parser.parse_args()
    os.umask(0o077)
    root = private_dir(args.output)
    config = json.loads(args.protocol.read_text())
    sources = source_hashes()
    freeze = dict(started=datetime.now(timezone.utc).isoformat(), protocol=config, sources=sources,
                  actual_protocol_sha256=digest(args.protocol),
                  packages={n: importlib.metadata.version(n) for n in ('numpy', 'pillow', 'opencv-python-headless')})
    write(root/'freeze.json', freeze)
    print('frozen', root, flush=True)
    records = prepare(root, config)
    write(root/'inference-freeze.json', dict(manifest_sha256=digest(root/'manifest.json'), sources=sources))
    rows = features(root, records)
    summary = dict(schema=1, protocol=config['id'], source_hashes=sources,
                   manifest_sha256=digest(root/'manifest.json'), freeze_sha256=digest(root/'freeze.json'),
                   inference_freeze_sha256=digest(root/'inference-freeze.json'),
                   candidates={}, data_rights='synthetic + existing author-published CC-BY-SA-2.5 MIDV DEV',
                   test_access=False, real_attack_examples=0, production_promotion=False)
    # Train/calibrate ALL models before evaluating any DEV outcomes.
    models = {}
    for candidate in config['candidates']:
        model = None if candidate=='constant_unknown' else train(config, records, rows, candidate)
        models[candidate] = model
        if model is not None:
            model['provenance'] = dict(manifest_sha256=summary['manifest_sha256'], sources=sources)
            write(root/(candidate+'.model.json'), model)
    write(root/'models-frozen.json', {c:digest(root/(c+'.model.json')) for c,m in models.items() if m is not None})
    for candidate, model in models.items():
        scores = {}
        for split in ('calibration', 'dev', 'real_dev'):
            aggregate, predictions = evaluate(model, records, rows, split)
            scores[split] = aggregate
            write(root/(candidate+'.'+split+'.predictions.json'), predictions)
        summary['candidates'][candidate] = dict(metrics=scores,
            model_sha256=digest(root/(candidate+'.model.json')) if model else None,
            thresholds=model['thresholds'] if model else None)
    if source_hashes() != sources:
        raise ValueError('source changed during run')
    # Catch input mutations, including after a sample was inferred.
    for r in records:
        p = Path(r['path']) if r['split']=='real_dev' else safe_path(root, r['path'])
        if digest(p) != r['sha256']:
            raise ValueError('input changed during run')
    write(root/'summary.json', summary)
    print(json.dumps({c:{s:{k:v for k,v in q.items() if k!='by_condition'} for s,q in r['metrics'].items()} for c,r in summary['candidates'].items()}, indent=2), flush=True)

if __name__ == '__main__':
    main()
