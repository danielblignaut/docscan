#!/usr/bin/env python3
"""DEV-only paired type experiment; raw outputs stay in a fresh private run root."""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from candidates import classify, keyword_type

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def type_row(iid, truth, baseline, candidate):
    return dict(id=iid, truth=truth, baseline=baseline, candidate=candidate,
                baseline_exact=baseline == truth, candidate_exact=candidate == truth,
                recovered=baseline != truth and candidate == truth,
                regressed=baseline == truth and candidate != truth,
                false_bank_baseline=truth != 'bank_statement' and baseline == 'bank_statement',
                false_bank_candidate=truth != 'bank_statement' and candidate == 'bank_statement')


def summarize(rows):
    return {'denominator': len(rows), **{k: sum(r[k] for r in rows) for k in
        ['baseline_exact', 'candidate_exact', 'recovered', 'regressed', 'false_bank_baseline', 'false_bank_candidate']},
        'nonbank_denominator': sum(r['truth'] != 'bank_statement' for r in rows), 'items': rows}


def predict_type(page, fields, config):
    if not fields or page.get('error') or not page.get('words'):
        return None
    return classify(page['words'], page.get('page_size'), fields.get('document_type'), config)


def native(binary, model, rows, today='2026-10-15'):
    try:
        p = subprocess.run([str(binary), '--tagger=' + str(model), '--today=' + today],
            input='\n'.join(json.dumps(r) for r in rows), text=True, capture_output=True,
            env=dict(os.environ, RTEN_NUM_THREADS='1', RAYON_NUM_THREADS='1'), timeout=600)
        if p.returncode:
            return {}, {'process_returncode': p.returncode, 'stderr_sha256': hashlib.sha256(p.stderr.encode()).hexdigest()}
        output = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
        return {r['id']: r for r in output}, None
    except (subprocess.TimeoutExpired, ValueError):
        return {}, {'error': 'timeout_or_malformed'}


def score_checked(dev, caps, truths, outputs):
    """Retain the frozen scorer, but never credit missing native decisions."""
    metrics = dev.poa.score('dev', caps, truths, outputs)
    invalid = set()
    for cap in caps:
        row = outputs[cap['id']]
        results = [(cap['id'], row['capture'])]
        results += [(f"{cap['id']}:{i}", r) for i, r in enumerate(row['frames'])]
        for iid, result in results:
            if not result.get('fields') or not isinstance((result.get('verify') or {}).get('accepted'), bool):
                invalid.add(iid)
    for key, metric in list(metrics.items()):
        if metric.get('kind') == 'rate' and any(i in invalid for i in metric['ids']):
            metrics[key] = dev.poa.m_rate(metric['ids'],
                [ok and iid not in invalid for iid, ok in zip(metric['ids'], metric['ok'])],
                desc=metric['desc'], better=metric['better'], unit=metric['unit'])
    return metrics


def page_text(words):
    out = ''; last = None
    for word in words:
        if last is not None: out += '\n' if last != word['line'] else ' '
        out += word['text']; last = word['line']
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-root', type=Path, required=True)
    ap.add_argument('--run-root', type=Path, required=True)
    ap.add_argument('--public-root', type=Path, default=Path('/tmp/docscan-public-data/poa-model-bound-v1'))
    args = ap.parse_args()
    os.umask(0o077)
    run = args.run_root.resolve()
    if run == REPO or REPO in run.parents:
        raise ValueError('Raw output must stay outside repository')
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = args.build_root / 'source'
    model = source / 'models/poa-tagger.onnx'
    (run / 'bin').mkdir()
    for name in ['poa_capture', 'poa_fields']:
        shutil.copy2(args.build_root / 'target/release/examples' / name, run / 'bin' / name)
    freeze = json.loads((HERE / 'candidate-freeze.json').read_text())
    for name, digest in freeze['files'].items():
        assert sha(HERE / name) == digest, 'Candidate was modified after freeze'
    config = json.loads((HERE / 'protocol.json').read_text())
    os.environ['DOCSCAN_EXAMPLES'] = str(run / 'bin')
    sys.path.insert(0, str(source / 'eval'))
    import poa_extraction_dev as dev
    # Only the fixed DEV loader decodes cache entries; no glob across split roots.
    manifest, caps, truths, pages = dev.load_frozen_dev()
    public = module('public_referee', REPO / 'experiments/public_poa/harness.py')
    public.check_freeze(args.public_root)
    public.completed_evaluation(args.public_root)
    for name in ['harness.py', 'protocol.json', 'source-pins.json']:
        assert sha(REPO / 'experiments/public_poa' / name) == sha(source / 'experiments/public_poa' / name)
    inputs = [args.public_root / 'freeze.json', args.public_root / 'truth.json', args.public_root / 'text-layer.json']
    inputs += [args.public_root / 'baseline' / (v + '.json') for v in public.VARIANTS]
    pins = {str(p): sha(p) for p in inputs}
    provenance = {
        'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'candidate_freeze': freeze, 'run_script_sha256': sha(HERE / 'run.py'),
        'source': json.loads((args.build_root / 'build-source.json').read_text()),
        'binaries': {p.name: sha(p) for p in (run / 'bin').iterdir()}, 'model_sha256': sha(model),
        'synthetic_manifest': manifest['tree_sha256'], 'synthetic_ocr_digest': dev.RECORDS_DIGEST,
        'public_inputs': pins, 'referees': {str(p.relative_to(source)): sha(p) for p in
            [source / 'eval/poa_extraction_dev.py', source / 'eval/poa_eval.py', source / 'bench/suites/poa.py', source / 'experiments/public_poa/harness.py']},
    }
    write(run / 'freeze.json', provenance)
    model_before = public.model_state()
    payloads = [{'id': c['id'], 'customer': truths[c['id']]['customer'],
        'frames': [{k: pages[f['path']].get(k) for k in ('words', 'page_size', 'page', 'error', 'fallback')} for f in c['frames']]} for c in caps]
    baseline, error = native(run / 'bin/poa_capture', model, payloads)
    write(run / 'synthetic-baseline-raw.json', {'outputs': baseline, 'error': error})
    for cap in caps:
        baseline.setdefault(cap['id'], {'id': cap['id'], 'capture': {'fields': None, 'verify': None},
                                      'frames': [{'fields': None, 'verify': None} for _ in cap['frames']]})
    report = {'provenance': provenance, 'scope': config['scope'], 'errors': {'synthetic': error}, 'candidates': {}}
    report['synthetic_baseline_metrics'] = score_checked(dev, caps, truths, baseline)
    public_protocol = json.loads((REPO / 'experiments/public_poa/protocol.json').read_text())
    raw_truth = json.loads((args.public_root / 'truth.json').read_text())
    truth = public.truth_fields(raw_truth)
    public_pages = {v: json.loads((args.public_root / 'baseline' / (v + '.json')).read_text())['page'] for v in public.VARIANTS}
    public_pages['native_text'] = json.loads((args.public_root / 'text-layer.json').read_text())
    public_base = {}
    for variant, page in public_pages.items():
        output, err = native(run / 'bin/poa_fields', model, [{'id': variant, 'words': page.get('words'), 'page_size': page.get('page_size')}])
        public_base[variant] = {'page': output.get(variant, {'error': err or 'missing'}),
            'verification': public.verification(run, page, raw_truth, public_protocol)}
    write(run / 'public-baseline-raw.json', public_base)
    report['public_baseline'] = public.aggregate_rows([public_base[v] for v in public.VARIANTS], truth)
    report['native_text_baseline'] = public.aggregate_rows([public_base['native_text']], truth)
    # Port parity is checked against native types on all public and synthetic frames.
    parity = []
    for cap in caps:
        for i, frame in enumerate(cap['frames']):
            page = pages[frame['path']]; fields = baseline[cap['id']]['frames'][i].get('fields')
            if fields:
                parity.append(keyword_type(page_text(page.get('words', []))) == fields['document_type'])
    report['keyword_port_parity'] = {'matched': sum(parity), 'denominator': len(parity)}
    for cfg in config['candidates']:
        candidate = copy.deepcopy(baseline); frame_rows = []; cap_rows = []
        for cap in caps:
            cid = cap['id']; target = candidate[cid]; wanted = truths[cid]['fields'].get('document_type')
            assert wanted is not None, 'Supplemental type requires independent truth'
            types = []
            for i, frame in enumerate(cap['frames']):
                fields = target['frames'][i].get('fields')
                btype = fields.get('document_type') if fields else None
                ctype = predict_type(pages[frame['path']], fields, cfg); types.append(ctype)
                if fields: fields['document_type'] = ctype
                frame_rows.append(type_row(f'{cid}:{i}', wanted, btype, ctype))
            fields = target['capture'].get('fields'); btype = fields.get('document_type') if fields else None
            picked = target['capture'].get('picked', [])
            votes = Counter(types[i] for i in picked)
            ctype = btype
            if votes:
                top, n = votes.most_common(1)[0]
                if n > len(picked) / 2: ctype = top
            if fields: fields['document_type'] = ctype
            cap_rows.append(type_row(cid, wanted, btype, ctype))
        metrics = score_checked(dev, caps, truths, candidate)
        public_candidate = copy.deepcopy(public_base)
        field_rows = []
        for variant, row in public_candidate.items():
            for method in public.METHODS:
                fields = row['page'].get(method, {}).get('fields')
                if fields: fields['document_type'] = predict_type(public_pages[variant], fields, cfg)
                _, before = public.field_scores(public_base[variant]['page'], method, truth)
                _, after = public.field_scores(row['page'], method, truth)
                field_rows.append({'id': variant, 'method': method, 'denominator': len(public.FIELDS),
                    'baseline': before, 'candidate': after,
                    'recovered': [k for k in before if not before[k] and after[k]],
                    'regressed': [k for k in before if before[k] and not after[k]]})
        report['candidates'][cfg['id']] = {
            'config': cfg, 'synthetic_capture_type': summarize(cap_rows), 'synthetic_frame_type': summarize(frame_rows),
            'synthetic_metrics': metrics, 'public': public.aggregate_rows([public_candidate[v] for v in public.VARIANTS], truth),
            'native_text': public.aggregate_rows([public_candidate['native_text']], truth), 'public_field_items': field_rows,
            'acceptance_policy': 'Independent shipped verification replayed above; type-only postprocessing cannot affect it. Not a candidate integrated into the verifier.',
        }
        write(run / (cfg['id'] + '-raw.json'), {'synthetic': candidate, 'public': public_candidate})
    assert model_before == public.model_state()
    assert sha(model) == provenance['model_sha256']
    for path, digest in pins.items(): assert sha(path) == digest
    for name, digest in freeze['files'].items(): assert sha(HERE / name) == digest
    for name, digest in provenance['binaries'].items(): assert sha(run / 'bin' / name) == digest
    public.check_freeze(args.public_root); public.completed_evaluation(args.public_root)
    report['completed_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report['raw_output_sha256'] = {p.name: sha(p) for p in run.glob('*-raw.json')}
    write(run / 'report.json', report)
    print(json.dumps({'baseline_public': report['public_baseline'], 'port_parity':report['keyword_port_parity'],
        'candidates': {k: {s: {a: b for a,b in v[s].items() if a != 'items'} for s in ['synthetic_capture_type','synthetic_frame_type']} for k,v in report['candidates'].items()}}, indent=2))

if __name__ == '__main__':
    main()
