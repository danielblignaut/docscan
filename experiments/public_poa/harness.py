#!/usr/bin/env python3
"""Frozen external DEV referee. Raw data and predictions are always outside git."""
import argparse
import collections
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unicodedata
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_ROOT = Path('/tmp/docscan-public-data/poa-synthesized-v1')
VARIANTS = ('clean', 'scanned', 'fax')
FIELDS = ('holder_name', 'address.street', 'address.city', 'address.postal_code',
          'issuer', 'account_number', 'document_type', 'statement_period.from', 'statement_period.to')
METHODS = ('rules', 'tagger')
MODELS = ('text-detection.rten', 'text-recognition.rten', 'text-detection-page.onnx', 'poa-tagger.onnx')
BINARIES = ('poa', 'poa_fields', 'poa_capture')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    path.chmod(0o600)


def private_root(root):
    root = root.resolve()
    if root == REPO or REPO in root.parents:
        raise ValueError('Raw data and predictions must be outside the repository')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    return root


def norm(value):
    if value is None:
        return ''
    s = unicodedata.normalize('NFKC', str(value)).casefold()
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in s).split())


def at(record, key):
    for part in key.split('.'):
        if not isinstance(record, dict):
            return None
        record = record.get(part)
    return record


def truth_fields(truth):
    assert truth['_meta']['synthetic'] is True
    assert truth['_meta']['licence'] == 'CC-BY-4.0'
    masked = [x['value'] for x in truth['personal_data'] if x['type'] == 'ACCOUNT_NUMBER_MASKED']
    assert len(masked) == 1
    return {'holder_name': truth['account_holder'], 'address.street': truth['address']['street'],
            'address.city': truth['address']['city'], 'address.postal_code': truth['address']['zip'],
            'issuer': truth['bank_name'], 'account_number': masked[0],
            'document_type': truth['document_type'], 'statement_period.from': truth['period'][0],
            'statement_period.to': truth['period'][1]}


def field_scores(result, method, truth):
    fields = at(result, method + '.fields')
    read = bool(fields is not None and isinstance(fields, dict) and not result.get('error'))
    scores = {}
    for name in FIELDS:
        value = at(fields, name)
        scores[name] = bool(read and value is not None and (
            value == truth[name] if name.startswith('statement_period.') else norm(value) == norm(truth[name])))
    return read, scores


def run_json(cmd, *, payload=None, timeout=180):
    env = dict(os.environ, RAYON_NUM_THREADS='1', RTEN_NUM_THREADS='1')
    try:
        proc = subprocess.run([str(x) for x in cmd], input=json.dumps(payload) + '\n' if payload is not None else None,
                              text=True, capture_output=True, timeout=timeout, cwd=REPO, env=env)
    except subprocess.TimeoutExpired:
        return {'error': 'timeout'}
    except OSError as exc:
        return {'error': 'launch_error', 'detail': str(exc)}
    if proc.returncode:
        return {'error': 'process_failure', 'returncode': proc.returncode, 'stderr': proc.stderr}
    try:
        lines = proc.stdout.strip().splitlines()
        assert len(lines) == 1
        value = json.loads(lines[0])
        assert isinstance(value, dict)
        return value
    except (ValueError, AssertionError):
        return {'error': 'malformed_output', 'stdout': proc.stdout, 'stderr': proc.stderr}


def source_files(root, download=False):
    pins = json.loads((HERE / 'source-pins.json').read_text())
    for name, pin in pins.items():
        path = root / name
        if not path.exists():
            if not download:
                raise ValueError(f'Missing pinned source: {name}')
            req = urllib.request.Request(pin['url'], headers={'User-Agent': 'docscan-public-poa-research/1.0'})
            with urllib.request.urlopen(req, timeout=40) as response:
                data = response.read(10_000_001)
            if len(data) > 10_000_000 or hashlib.sha256(data).hexdigest() != pin['sha256']:
                raise ValueError(f'Upstream bytes changed: {name}; explicit new protocol required')
            path.write_bytes(data)
        assert sha(path) == pin['sha256'], f'Pinned source changed: {name}'
        path.chmod(0o600)


def prepare(root):
    import fitz
    assert fitz.__version__ == '1.26.7'
    if (root / 'freeze.json').exists():
        raise ValueError('Already frozen; prepare refuses to overwrite this round')
    source_files(root, download=True)
    truth_fields(json.loads((root / 'truth.json').read_text()))
    metadata = {}
    for variant in VARIANTS:
        with fitz.open(root / (variant + '.pdf')) as doc:
            assert len(doc) == 1
            page = doc[0]
            pix = page.get_pixmap(dpi=150, alpha=False)
            pix.save(root / (variant + '.png'))
            (root / (variant + '.png')).chmod(0o600)
            words = page.get_text('words', sort=True)
            metadata[variant] = {'pages': len(doc), 'image_size': [pix.width, pix.height], 'text_layer_words': len(words)}
            if variant == 'clean':
                lines, converted = {}, []
                for x0, y0, x1, y1, text, block, line, _ in words:
                    line_id = lines.setdefault((block, line), len(lines))
                    converted.append({'text': text, 'x': x0, 'y': y0, 'w': x1-x0, 'h': y1-y0, 'line': line_id})
                assert converted
                write(root / 'text-layer.json', {'words': converted,
                       'page_size': [round(page.rect.width), round(page.rect.height)]})
            else:
                assert not words, 'Publisher image-only claim does not hold'
    (root / 'bin').mkdir(mode=0o700, exist_ok=True)
    for binary in BINARIES:
        shutil.copy2(REPO / 'docscan/target/release/examples' / binary, root / 'bin' / binary)
        (root / 'bin' / binary).chmod(0o700)
    write(root / 'preparation.json', metadata)
    print(json.dumps(metadata))


def freeze(root):
    import fitz
    source_files(root)
    if (root / 'freeze.json').exists():
        raise ValueError('Freeze is immutable; use a new version for changed referees')
    protocol = json.loads((HERE / 'protocol.json').read_text())
    assert protocol['scored_fields'] == list(FIELDS)
    files = {str(p.relative_to(root)): sha(p) for p in
             [root / (v + ext) for v in VARIANTS for ext in ('.pdf', '.png')] +
             [root / 'truth.json', root / 'text-layer.json'] + [root / 'bin' / b for b in BINARIES]}
    result = {'version': protocol['version'], 'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'split': 'DEV', 'files': files, 'pymupdf': fitz.__version__,
              'referee': {p.name: sha(p) for p in [HERE / 'harness.py', HERE / 'protocol.json', HERE / 'source-pins.json']},
              'models': {m: sha(REPO / 'models' / m) for m in MODELS},
              'repo_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
              'binary_provenance': 'Existing release artifacts copied before inference; build-to-HEAD correspondence unverified; hashes identify executed bytes.'}
    write(root / 'freeze.json', result)
    print('Frozen before inference:', sha(root / 'freeze.json'))


def check_freeze(root):
    record = json.loads((root / 'freeze.json').read_text())
    for name, digest in record['referee'].items():
        assert sha(HERE / name) == digest, f'Referee changed after freeze: {name}'
    for name, digest in record['files'].items():
        assert sha(root / name) == digest, f'Input/binary changed after freeze: {name}'
    for name, digest in record['models'].items():
        assert sha(REPO / 'models' / name) == digest, f'Model changed after freeze: {name}'
    return record


def customer(truth, case):
    address = {'street': truth['address']['street'], 'city': truth['address']['city'],
               'postal_code': truth['address']['zip']}
    value = {'name': truth['account_holder'], 'address': address}
    if case == 'wrong_person':
        value['name'] = 'Zelmira Quenwick'
    elif case == 'wrong_address':
        value['address']['street'] = re.sub(r'^\d+', lambda m: str(int(m[0]) + 1000), address['street'])
        assert value['address']['street'] != truth['address']['street']
    return value


def verification(root, page, truth, protocol):
    results = {}
    for case in ('matching', 'wrong_person', 'wrong_address', 'old'):
        if page.get('error') or not page.get('words') or not page.get('page_size'):
            results[case] = {'error': 'no_reading'}
            continue
        today = protocol['old_today'] if case == 'old' else protocol['today']
        results[case] = run_json([root / 'bin/poa_capture', '--tagger=' + str(REPO / 'models/poa-tagger.onnx'),
                                 '--today=' + today, '--max-frames=1', '--min-frames=1'],
                                payload={'id': case, 'customer': customer(truth, case), 'frames': [page]},
                                timeout=protocol['timeout_seconds'])
    return results


def evaluate(root):
    check_freeze(root)
    protocol = json.loads((HERE / 'protocol.json').read_text())
    truth = json.loads((root / 'truth.json').read_text())
    outdir = root / 'baseline'
    if outdir.exists():
        raise ValueError('Baseline already exists; preserve first run')
    outdir.mkdir(mode=0o700)
    tagger = '--tagger=' + str(REPO / 'models/poa-tagger.onnx')
    for variant in VARIANTS:
        page = run_json([root / 'bin/poa', '--flat', '--words', tagger, '--today=' + protocol['today'],
                         root / (variant + '.png')], timeout=protocol['timeout_seconds'])
        write(outdir / (variant + '.json'), {'page': page, 'verification': verification(root, page, truth, protocol)})
        print(variant + ': recorded', flush=True)
    words = json.loads((root / 'text-layer.json').read_text())
    result = run_json([root / 'bin/poa_fields', tagger, '--today=' + protocol['today']], payload=words,
                      timeout=protocol['timeout_seconds'])
    write(outdir / 'text-layer.json', {'page': result, 'verification': verification(root, words, truth, protocol)})
    check_freeze(root)
    aggregate(root)


def verification_score(result):
    check = at(result, 'capture.verify')
    if result.get('error') or not isinstance(check, dict) or not isinstance(check.get('accepted'), bool):
        return {'valid': False, 'accepted': False, 'reasons': [], 'date': None, 'name': None, 'address': None}
    return {'valid': True, **check}


def aggregate_rows(rows, truth):
    aggregate = {}
    for method in METHODS:
        counts = collections.Counter({name: 0 for name in FIELDS})
        readable = all_fields = holder_address = 0
        dates = collections.Counter()
        for row in rows:
            read, scores = field_scores(row['page'], method, truth)
            readable += read
            counts.update({k: int(v) for k, v in scores.items()})
            all_fields += all(scores.values())
            holder_address += all(scores[k] for k in FIELDS[:4])
            date = at(row['page'], method + '.fields.document_date')
            dates['missing' if not date else 'period_end' if date == truth['statement_period.to'] else
                  'period_start' if date == truth['statement_period.from'] else 'other'] += 1
        n = len(rows)
        aggregate[method] = {'denominator': n, 'readable': readable, 'failed_or_no_reading': n-readable,
                             'field_exact': dict(counts), 'field_opportunities': n * len(FIELDS),
                             'field_exact_total': sum(counts.values()), 'all_fields_exact': all_fields,
                             'holder_address_exact': holder_address, 'document_date_unscored': dict(dates)}
    checks = {case: [verification_score(row['verification'].get(case, {})) for row in rows]
              for case in ('matching', 'wrong_person', 'wrong_address', 'old')}
    metrics = {}
    for case, values in checks.items():
        metrics[case] = {'denominator': len(rows), 'valid_decisions': sum(v['valid'] for v in values),
                         'accepted': sum(v['valid'] and v['accepted'] for v in values),
                         'rejected': sum(v['valid'] and not v['accepted'] for v in values),
                         'failed_or_no_decision': sum(not v['valid'] for v in values),
                         'paired_matching_accept_and_reject': None if case == 'matching' else
                         sum(m['valid'] and m['accepted'] and v['valid'] and not v['accepted']
                             for m, v in zip(checks['matching'], values)),
                         'old_date_evidence': sum(v['valid'] and isinstance(v.get('date'), dict)
                                                  and not v['date'].get('recent', True)
                                                  and v['date'].get('age_days', 0) > 0 for v in values)}
    aggregate['customer_verification'] = metrics
    return aggregate


def aggregate(root):
    record = check_freeze(root)
    truth = truth_fields(json.loads((root / 'truth.json').read_text()))
    rows = [json.loads((root / 'baseline' / (v + '.json')).read_text()) for v in VARIANTS]
    diagnostic = json.loads((root / 'baseline/text-layer.json').read_text())
    result = {'protocol': record['version'], 'split': 'DEV', 'independent_identities': 1,
              'freeze_sha256': sha(root / 'freeze.json'), 'provenance': record,
              'raster_ocr': aggregate_rows(rows, truth),
              'by_variant': {v: aggregate_rows([row], truth) for v, row in zip(VARIANTS, rows)},
              'text_layer_diagnostic': aggregate_rows([diagnostic], truth),
              'limitations': json.loads((HERE / 'protocol.json').read_text())['limits']}
    write(root / 'aggregate.json', result)
    print(json.dumps(result['raster_ocr'], indent=2))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'freeze', 'evaluate', 'aggregate'])
    parser.add_argument('--data-root', type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    root = private_root(args.data_root)
    {'prepare': prepare, 'freeze': freeze, 'evaluate': evaluate, 'aggregate': aggregate}[args.command](root)


if __name__ == '__main__':
    main()
