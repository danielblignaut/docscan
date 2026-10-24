#!/usr/bin/env python3
"""One frozen London DEV matching hypothesis; no fitting and no TEST inputs.

This intentionally does not call public_face.prepare (which writes shared data)
or public_face.score (which fits research thresholds). Historical caches are
read-only and eligible only when they correspond to this exact executable.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

os.environ.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
import numpy as np
from PIL import Image, ImageFilter, __version__ as pillow_version

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / 'experiments/public_face'
sys.path.insert(0, str(PUBLIC))
import artifacts
import evaluate as referee

HERE = Path(__file__).resolve().parent
DATA = Path('/tmp/docscan-public-data/face-london')
PRIVATE = Path('/tmp/docscan-public-data/research-face')
PROTOCOL = HERE / 'matching_protocol_v1.json'
HISTORICAL = PUBLIC / 'results/london-v2-production-pair.json'
digest = artifacts.digest


def write_json(path, value):
    with path.open('x') as out:
        json.dump(value, out, indent=2, allow_nan=False)
        out.write('\n')


def utc():
    return datetime.now(timezone.utc).isoformat()


def row_key(row):
    return row['split'], row['id'], row['pose'], row['condition']


def unique_index(rows):
    keys = [row_key(r) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate identity/pose/condition row')
    return {key: i for i, key in enumerate(keys)}


def corresponding_rows(expected, actual):
    """Join by identity/pose/condition, not position; reject an incomplete view."""
    index = unique_index(actual)
    if set(index) != set(unique_index(expected)):
        raise ValueError('View correspondence differs')
    return np.array([index[row_key(r)] for r in expected])


def normalized(vectors, found):
    vectors = np.asarray(vectors, dtype=np.float32).copy()
    found = np.asarray(found, dtype=bool).copy()
    if vectors.ndim != 2 or found.shape != (len(vectors),):
        raise ValueError('Embedding/flag shape mismatch')
    with np.errstate(over='ignore', invalid='ignore'):
        norm = np.linalg.norm(vectors, axis=1)
    found &= np.isfinite(vectors).all(axis=1) & np.isfinite(norm) & (norm > 1e-12)
    vectors[~found] = 0
    vectors /= np.where(found, norm, 1)[:, None]
    return vectors, found


def aggregate_views(expected, views):
    if len(views) != 3:
        raise ValueError('Exactly three frozen views required')
    vectors, usable = [], []
    for rows, vec, found in views:
        order = corresponding_rows(expected, rows)
        v, f = normalized(vec[order], found[order])
        vectors.append(v)
        usable.append(f)
    return normalized(np.mean(np.stack(vectors), axis=0), np.all(usable, axis=0))


def pair_scores(probes, pv, pf, refs, rv, rf):
    unique_index(probes)
    unique_index(refs)
    pids, rids = [r['id'] for r in probes], [r['id'] for r in refs]
    if len(set(pids)) != len(pids) or len(set(rids)) != len(rids) or set(pids) != set(rids):
        raise ValueError('Need one probe and reference for every identity')
    splits = {r['split'] for r in probes + refs}
    if len(splits) != 1 or not splits <= {'calibration', 'validation'}:
        raise ValueError('Identity groups must stay within one DEV split')
    if any(r['pose'] != 'neutral' for r in probes) or any(r['pose'] != 'smile' for r in refs):
        raise ValueError('Expected neutral probes and smile references')
    if len({r['condition'] for r in probes}) != 1:
        raise ValueError('Do not pool conditions')
    if pv.shape != (len(probes), rv.shape[1]) or len(rv) != len(refs):
        raise ValueError('Pair dimensions differ')
    # Inputs already normalized once at native loading / aggregation.
    scores = pv @ rv.T
    scores[~(pf[:, None] & rf[None, :])] = -np.inf
    labels = np.equal.outer(pids, rids)
    return scores, labels


def gamma_image(image, gamma):
    lut = np.rint(255 * (np.arange(256, dtype=np.float64) / 255) ** gamma).clip(0, 255).astype(np.uint8)
    return Image.fromarray(lut[np.asarray(image.convert('RGB'))])


def degraded_bytes(source, condition):
    with Image.open(source) as image:
        image = image.convert('RGB').resize((condition['side'],) * 2, Image.Resampling.LANCZOS)
        image = image.convert('L').convert('RGB').filter(ImageFilter.GaussianBlur(condition['blur']))
        if condition['contrast'] != 1:
            pixels = np.asarray(image, dtype=np.float64)
            image = Image.fromarray(np.rint(127.5 + condition['contrast'] * (pixels - 127.5)).clip(0, 255).astype(np.uint8))
        out = io.BytesIO()
        image.save(out, format='JPEG', quality=condition['jpeg_quality'])
        return out.getvalue()


def prepare(config, folder):
    if digest(DATA / 'manifest.json') != config['source_manifest_sha256']:
        raise ValueError('Source manifest differs')
    if digest(DATA / 'protocol-v1.json') != config['historical_rows_sha256']:
        raise ValueError('Historical rows differ')
    manifest = json.loads((DATA / 'manifest.json').read_text())
    if manifest['revision'] != config['source_revision'] or len(manifest['files']) != 204:
        raise ValueError('Unexpected source cohort')
    sources = {}
    for row in manifest['files']:
        path = DATA / row['path']
        if not path.resolve().is_relative_to(DATA) or digest(path) != row['sha256']:
            raise ValueError('Source file changed or escaped private source root')
        blob = path.read_bytes()
        if len(blob) != row['bytes'] or hashlib.sha1(b'blob ' + str(len(blob)).encode() + b'\0' + blob).hexdigest() != row['git_blob']:
            raise ValueError('Pinned git source differs')
        identity, pose = path.stem.split('_')[0], path.parent.name
        key = identity, pose
        if key in sources:
            raise ValueError('Duplicate source')
        sources[key] = path
    identities = sorted({key[0] for key in sources}, key=lambda x: hashlib.sha256(('london-dev-v1:' + x).encode()).hexdigest())
    if len(identities) != 102:
        raise ValueError('Expected 102 identities')
    historical = json.loads((DATA / 'protocol-v1.json').read_text())
    hindex = unique_index(historical)
    rows, old_expected = [], []
    (folder / 'images').mkdir(mode=0o700)
    for number, identity in enumerate(identities):
        split = 'calibration' if number < 51 else 'validation'
        for pose, source_pose in [('neutral', 'neutral_front'), ('smile', 'smiling_front')]:
            source = sources[identity, source_pose]
            for condition in config['conditions'] if pose == 'neutral' else config['conditions'][:1]:
                name = condition['name']
                path = source
                if name != 'original':
                    blob = degraded_bytes(source, condition)
                    path = DATA / 'derived-v1' / f'{identity}-{name}.jpg'
                    if name == 'document_hard96':
                        path = folder / 'images' / f'{identity}-{name}.jpg'
                        with path.open('xb') as out:
                            out.write(blob)
                    elif path.read_bytes() != blob:
                        raise ValueError('Prior degradation does not correspond exactly')
                row = dict(id=identity, split=split, pose=pose, condition=name, path=str(path), sha256=digest(path))
                rows.append(row)
                if name != 'document_hard96':
                    if historical[hindex[row_key(row)]] != row:
                        raise ValueError('Historical row correspondence failed')
                    old_expected.append(row)
    if old_expected != historical:
        raise ValueError('Historical row order differs')
    write_json(folder / 'rows.json', rows)
    return rows, historical


def verify_rows(rows):
    for row in rows:
        if digest(Path(row['path'])) != row['sha256']:
            raise ValueError('Inference input changed')


def read_native(path, count):
    vec, found, items = referee.read_embeddings(path, count)
    # Inherited native format has one metadata row per input; unusable presence
    # must reject even if found is true. No live-camera quality gating here.
    for i, item in enumerate(items):
        presence = item.get('presence', 1.0)
        found[i] &= isinstance(presence, (int, float)) and np.isfinite(presence) and presence >= .5
    return normalized(vec, found)


def cache_eligible(run, historical, rows, variant, jobs):
    key = referee.cache_key(run.binary_sha256, run.model_hashes, rows, variant, jobs)
    name = 'unflipped_live' if variant == 'iris' else 'flip_averaged_photo'
    return (historical['binary_sha256'] == run.binary_sha256
            and historical['models'] == run.model_hashes
            and historical['source_manifest_sha256'] == digest(DATA / 'manifest.json')
            and historical['protocol_sha256'] == digest(DATA / 'protocol-v1.json')
            and historical['run'][name]['cache_key'] == key), key


def native(run, folder, rows, variant, jobs, name, old_rows, prior):
    run.verify()
    verify_rows(rows)
    eligible, old_key = cache_eligible(run, prior, old_rows, variant, jobs)
    old_folder = DATA / 'runs' / old_key
    old_index = unique_index(old_rows)
    is_subset = all(row_key(row) in old_index and old_rows[old_index[row_key(row)]] == row for row in rows)
    start = time.monotonic()
    if eligible and is_subset:
        if (old_folder / 'images.txt').read_text().splitlines() != [r['path'] for r in old_rows]:
            raise ValueError('Historical shard input order changed')
        files = [old_folder / f'{i}.f32{s}' for i in range(jobs) for s in ('', '.json')]
        hashes = {str(path): digest(path) for path in files}
        parts = [read_native(old_folder / f'{i}.f32', len(old_rows) * (i + 1) // jobs - len(old_rows) * i // jobs) for i in range(jobs)]
        order = [old_index[row_key(row)] for row in rows]
        vec = np.concatenate([p[0] for p in parts])[order]
        found = np.concatenate([p[1] for p in parts])[order]
        mode = 'exact historical cache read-only'
    else:
        destination = folder / name
        destination.mkdir(mode=0o700)
        paths = destination / 'images.txt'
        paths.write_text('\n'.join(r['path'] for r in rows) + '\n')
        def shard(i):
            out = destination / f'{i}.f32'
            count = len(rows) * (i + 1) // jobs - len(rows) * i // jobs
            with run.staged_output(out, ('', '.json')) as pending:
                cmd = [str(run.binary), '--models', str(run.models_dir), '--recogniser', 'sface_int8.onnx:sface_int8:sface', '--no-antispoof', 'embed', str(paths), str(pending), '--shard', f'{i}/{jobs}']
                if variant == 'flip':
                    cmd.append('--flip')
                result = subprocess.run(cmd, env=dict(os.environ, RTEN_NUM_THREADS='1', RAYON_NUM_THREADS='1'), capture_output=True, timeout=1800)
                (destination / f'{i}.log').write_bytes(result.stdout + result.stderr)
                result.check_returncode()
                read_native(pending, count)
            return read_native(out, count)
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            parts = list(pool.map(shard, range(jobs)))
        vec, found = np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts])
        files = [destination / f'{i}.f32{s}' for i in range(jobs) for s in ('', '.json')]
        hashes = {str(path): digest(path) for path in files}
        mode = 'fresh native inference'
    verify_rows(rows)
    run.verify()
    if hashes != {str(path): digest(path) for path in files}:
        raise ValueError('Embedding output changed during use')
    receipt = dict(mode=mode, rows=len(rows), usable=int(found.sum()), elapsed_s=round(time.monotonic() - start, 3), output_hashes=hashes,
                   historical_cache_eligible=bool(eligible and is_subset), variant=variant, jobs=jobs)
    print(json.dumps({'stage': name, **{k:v for k,v in receipt.items() if k != 'output_hashes'}}), flush=True)
    return vec, found, receipt


def frozen_thresholds(config):
    live = float(re.search(r'model: "sface_int8", threshold: ([0-9.]+)', (ROOT / 'docscan/src/face/mod.rs').read_text()).group(1))
    document = float(re.search(r'DOC_THRESHOLD = ([0-9.]+)', (ROOT / 'demo/src/face-models.ts').read_text()).group(1))
    if config['thresholds'] != dict(document=document, live=live):
        raise ValueError('Production thresholds differ from frozen protocol; do not tune')
    return config['thresholds']


def measure(config, folder, rows, ref_vec, ref_found, doc_vec, doc_found, cand_vec, cand_found):
    probes = [r for r in rows if r['pose'] == 'neutral']
    refs = [r for r in rows if r['pose'] == 'smile']
    result, private = {}, {}
    for condition in config['conditions']:
        name = condition['name']
        result[name] = {}
        for split in ('calibration', 'validation'):
            pi = [i for i,r in enumerate(probes) if r['split'] == split and r['condition'] == name]
            ri = [i for i,r in enumerate(refs) if r['split'] == split]
            if len(pi) != 51 or len(ri) != 51:
                raise ValueError('Incomplete split/condition')
            p, r = [probes[i] for i in pi], [refs[i] for i in ri]
            baseline, labels = pair_scores(p, doc_vec[pi], doc_found[pi], r, ref_vec[ri], ref_found[ri])
            candidate, other_labels = pair_scores(p, cand_vec[pi], cand_found[pi], r, ref_vec[ri], ref_found[ri])
            np.testing.assert_array_equal(labels, other_labels)
            entry = dict(genuine_pairs=int(labels.sum()), impostor_pairs=int((~labels).sum()), identities=51,
                         missing_reference=int((~ref_found[ri]).sum()), missing_probe_baseline=int((~doc_found[pi]).sum()), missing_probe_gamma_mean=int((~cand_found[pi]).sum()), operating_points={})
            for point, threshold in config['thresholds'].items():
                b, c = baseline >= threshold, candidate >= threshold
                transitions = {}
                for group, mask in [('genuine', labels), ('impostor', ~labels)]:
                    transitions[group] = dict(reject_to_accept=int((~b & c & mask).sum()), accept_to_reject=int((b & ~c & mask).sum()))
                entry['operating_points'][point] = dict(baseline=referee.rates(baseline, labels, threshold), gamma_mean=referee.rates(candidate, labels, threshold), paired_changes=transitions)
            result[name][split] = entry
            key = name + '_' + split
            private[key + '_baseline'] = baseline
            private[key + '_gamma_mean'] = candidate
            private[key + '_labels'] = labels
            private[key + '_probe_ids'] = np.array([row['id'] for row in p])
            private[key + '_reference_ids'] = np.array([row['id'] for row in r])
    np.savez_compressed(folder / 'pair_scores.npz', **private)
    np.savez_compressed(folder / 'embeddings.npz', baseline=doc_vec, baseline_found=doc_found, gamma_mean=cand_vec, gamma_found=cand_found, references=ref_vec, references_found=ref_found)
    support = True
    for name, conditions in result.items():
        for entry in conditions.values():
            b, c = (entry['operating_points']['document'][arm] for arm in ('baseline', 'gamma_mean'))
            support &= c['impostors_accepted'] <= b['impostors_accepted']
            support &= c['genuine_accepted'] > b['genuine_accepted'] if name == 'document_hard96' else c['genuine_accepted'] >= b['genuine_accepted']
    return result, bool(support)


def evaluate(binary, report, build_receipt):
    os.umask(0o077)
    if report.exists():
        raise ValueError('Refuse to overwrite results')
    if report.parent.resolve() != (HERE / 'results').resolve() or not report.name.startswith('matching_'):
        raise ValueError('Only new matching_ aggregate reports allowed')
    config = json.loads(PROTOCOL.read_text())
    if config['jobs'] not in (1, 2) or config['gammas'] != [.8, 1., 1.2]:
        raise ValueError('Frozen concurrency/candidate differs')
    frozen_thresholds(config)
    tracked = [Path(__file__), HERE / 'matching_test.py', PROTOCOL, PUBLIC / 'evaluate.py', PUBLIC / 'artifacts.py', HISTORICAL,
               DATA / 'manifest.json', DATA / 'protocol-v1.json', DATA / 'source-README.md', DATA / 'source-LICENSE.md',
               ROOT / 'docscan/src/face/mod.rs', ROOT / 'demo/src/face-models.ts', build_receipt]
    hashes = {str(p): digest(p) for p in tracked}
    prior = json.loads(HISTORICAL.read_text())
    with artifacts.pinned_run(binary, ROOT / 'models/face') as run:
        key = hashlib.sha256(json.dumps([hashes, run.binary_sha256, run.model_hashes], sort_keys=True).encode()).hexdigest()
        folder = PRIVATE / ('matching_' + key[:20])
        folder.mkdir(mode=0o700)
        frozen = dict(created_at=utc(), protocol_sha256=digest(PROTOCOL), runner_sha256=digest(Path(__file__)),
                      inputs=hashes, binary_sha256=run.binary_sha256, models=run.model_hashes,
                      build_receipt=json.loads(build_receipt.read_text()), python=platform.python_version(), numpy=np.__version__, pillow=pillow_version,
                      cpu_jobs=config['jobs'], native_threads_per_job=1,
                      historical_binary_sha256=prior['binary_sha256'], historical_cache_binary_matches=prior['binary_sha256'] == run.binary_sha256)
        write_json(folder / 'freeze.json', frozen)
        # Retain exact run/config/referee bytes before any native or cached scores.
        for name, path in [('runner.py',Path(__file__)),('protocol.json',PROTOCOL),('referee.py',PUBLIC/'evaluate.py'),('artifacts.py',PUBLIC/'artifacts.py')]:
            (folder / name).write_bytes(path.read_bytes())
        print(json.dumps({'stage':'predeclared-before-inference', 'freeze':str(folder/'freeze.json'), 'binary_sha256':run.binary_sha256, 'historical_cache_binary_matches':frozen['historical_cache_binary_matches']}), flush=True)
        rows, old_rows = prepare(config, folder)
        refs = [r for r in rows if r['pose'] == 'smile']
        docs = [r for r in rows if r['pose'] == 'neutral']
        # Old conditions are separate from hard96 so exactly corresponding caches
        # remain usable if the original executable is supplied in a later run.
        old_docs = [r for r in docs if r['condition'] != 'document_hard96']
        hard_docs = [r for r in docs if r['condition'] == 'document_hard96']
        rv, rf, rr = native(run, folder, refs, 'iris', config['jobs'], 'references', old_rows, prior)
        ov, of, old_receipt = native(run, folder, old_docs, 'flip', config['jobs'], 'baseline_old_conditions', old_rows, prior)
        hv, hf, hard_receipt = native(run, folder, hard_docs, 'flip', config['jobs'], 'baseline_hard96', old_rows, prior)
        order = corresponding_rows(docs, old_docs + hard_docs)
        dv, df = np.concatenate([ov,hv])[order], np.concatenate([of,hf])[order]
        views, receipts, all_rows = [(docs,dv,df)], [], list(rows)
        for gamma in (.8, 1.2):
            gamma_rows = []
            for row in docs:
                path = folder / 'images' / f'{row["id"]}-{row["condition"]}-gamma{gamma}.png'
                with Image.open(row['path']) as image:
                    gamma_image(image, gamma).save(path)
                gamma_rows.append(dict(row, path=str(path), sha256=digest(path)))
            gv, gf, receipt = native(run, folder, gamma_rows, 'flip', config['jobs'], f'gamma{gamma}', old_rows, prior)
            views.append((gamma_rows,gv,gf))
            receipts.append(dict(gamma=gamma, **receipt))
            all_rows.extend(gamma_rows)
        # Preserve the predeclared floating-point summation order: .8, 1, 1.2.
        cv, cf = aggregate_views(docs, [views[1], views[0], views[2]])
        metrics, support = measure(config, folder, rows, rv, rf, dv, df, cv, cf)
        write_json(folder / 'all_inference_rows.json', all_rows)
        historical_check = {}
        for name in ('original','document_gray','document_small'):
            point = 'live' if name == 'original' else 'document'
            historical_check[name] = {split: metrics[name][split]['operating_points'][point]['baseline'] == prior['metrics'][name]['shipped_threshold'][split] for split in ('calibration','validation')}
        verify_rows(all_rows)
        run.verify()
        if hashes != {str(p):digest(p) for p in tracked}:
            raise ValueError('A tracked protocol/source changed during run')
        output = dict(protocol=config['protocol'], completed_at=utc(), freeze=frozen, freeze_sha256=digest(folder/'freeze.json'),
                      inference=dict(references=rr, baseline_old_conditions=old_receipt, baseline_hard96=hard_receipt, gamma_views=receipts),
                      metrics=metrics, predeclared_support_criterion_met=support, historical_operating_point_metrics_equal=historical_check,
                      private_artifacts={str(folder/name):digest(folder/name) for name in ('pair_scores.npz','embeddings.npz','rows.json','all_inference_rows.json')},
                      limits=['102 same-session identities; two disjoint DEV halves, neither used to fit anything', '2550 dependent impostor pairs per cell; no population FAR or significance claim', 'three artificial print degradations, not real document/camera captures', 'gamma views are deterministic copies, not independent captures', 'native offline matching proxy excludes session gates and PAD', 'no browser/device latency or SOTA claim; no weights/thresholds changed'])
        report.parent.mkdir(exist_ok=True)
        write_json(report, output)
        print(json.dumps({'stage':'complete','report':str(report),'support_criterion_met':support}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--build-receipt', type=Path, required=True)
    parser.add_argument('--report', type=Path, default=HERE/'results/matching_photometric_v1.json')
    args = parser.parse_args()
    evaluate(args.binary, args.report, args.build_receipt)
