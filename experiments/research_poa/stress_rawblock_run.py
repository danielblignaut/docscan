"""Bounded private raw-block probe; immutable policy, source hashes and full accounting."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

from run import HERE, REPO, module, sha, write
from stress_rawblock import canonical_ocr_words, select

DATA = Path('/tmp/docscan-public-data')
CACHE = DATA / 'document-ocr-cache/c29db516a7f3ea091d5e120f31371c887ba8bc952283ab26b1f10ec633866c49'
PUBLIC = DATA / 'poa-model-bound-v1'
DOCS = REPO / 'experiments/public_documents'
REF = module('stress_document_referee', DOCS / 'evaluate.py')
PUBLIC_REF = module('stress_public_referee', REPO / 'experiments/public_poa/harness.py')


def inputs():
    manifest = json.loads((DOCS / 'manifest.json').read_text())
    rows = [r for r in manifest['fatura']['documents']
            if r['split'] == 'dev' or (r['split'] == 'train' and r['id'].endswith('_Instance0'))]
    assert Counter(r['split'] for r in rows) == {'train': 40, 'dev': 50}
    paths = [Path(__file__), HERE / 'stress_rawblock.py', HERE / 'run.py',
             DOCS / 'manifest.json', DOCS / 'protocol.json', DOCS / 'ocr-dev-v1.json',
             DOCS / 'evaluate.py', CACHE / 'validated.json', CACHE / 'reader',
             REPO / 'experiments/public_poa/harness.py', PUBLIC / 'freeze.json', PUBLIC / 'truth.json']
    marker = json.loads((CACHE / 'validated.json').read_text())
    assert marker['binary_sha256'] == sha(CACHE / 'reader')
    assert marker['manifest_sha256'] == sha(DOCS / 'ocr-dev-v1.json')
    assert marker['scorer_sha256'] == sha(DOCS / 'evaluate.py')
    for name, digest in marker['models'].items():
        path = REPO / 'models' / name
        assert sha(path) == digest
        paths.append(path)
    # Open only the 90 explicit eligible annotation members; never list archive members.
    archive = DATA / 'fatura/FATURA.zip'
    assert sha(archive) == manifest['fatura']['archive']['sha256']
    with zipfile.ZipFile(archive) as z:
        for row in rows:
            folder = DATA / 'fatura' / row['split']
            image, truth_path = folder / (row['id']+'.jpg'), folder / (row['id']+'.json')
            assert sha(image) == row['image_sha256']
            raw = z.read('invoices_dataset_final/Annotations/Original_Format/'+row['id']+'.json')
            assert hashlib.sha256(raw).hexdigest() == row['annotation_sha256']
            truth = json.loads(truth_path.read_text())
            expected = []
            for label, value in json.loads(raw).items():
                if label in {'OTHER', 'TABLE', 'LOGO'} or not isinstance(value, dict):
                    continue
                if not isinstance(value.get('text'), str) or not value.get('bbox'):
                    continue
                xs, ys = [p[0] for p in value['bbox']], [p[1] for p in value['bbox']]
                expected.append(dict(label=label, text=value['text'],
                                     bbox=[min(xs), truth['height']-max(ys), max(xs), truth['height']-min(ys)]))
            assert expected == truth['fields']
            paths += [image, truth_path]
            if row['split'] == 'dev':
                paths.append(CACHE / (row['id']+'.json'))
    PUBLIC_REF.check_freeze(PUBLIC)
    PUBLIC_REF.completed_evaluation(PUBLIC)
    paths += [PUBLIC / 'baseline' / (v+'.json') for v in PUBLIC_REF.VARIANTS]
    return rows, {str(p): sha(p) for p in paths}


def train_ocr(row, root):
    path = root / (row['id']+'.json')
    assert not path.exists()
    try:
        result = subprocess.run([str(CACHE / 'reader'), '--models='+str(REPO / 'models'), '--detail',
                                 str(DATA / 'fatura/train' / (row['id']+'.jpg'))],
                                capture_output=True, text=True, timeout=30,
                                env=dict(os.environ, RTEN_NUM_THREADS='1', RAYON_NUM_THREADS='1'))
        if result.returncode:
            raise ValueError('process_failed')
        output = json.loads(result.stdout)
        assert output['model_directory'] == str(REPO / 'models')
        assert output['engine'] == 'ppocr_v6_tiny' and isinstance(output['lines'], list)
    except (subprocess.TimeoutExpired, ValueError, KeyError, AssertionError) as error:
        output = {'error': type(error).__name__, 'lines': []}
    write(path, output)
    print(row['id'] + (' failed' if output.get('error') else ' complete'), flush=True)
    return row['id'], output


def inside(word, box):
    return (box[0] <= word['x']+word['w']/2 <= box[2] and
            box[1] <= word['y']+word['h']/2 <= box[3])


def aggregate(rows):
    eligible = [r for r in rows if r['eligible']]
    total = REF.summary([r['text_score'] for r in eligible])
    return dict(total= len(rows), eligible=len(eligible), ineligible=len(rows)-len(eligible),
                status=dict(Counter(r['selection']['status'] for r in rows)),
                eligible_status=dict(Counter(r['selection']['status'] for r in eligible)),
                ocr_failed=sum(r['ocr_failed'] for r in rows), text=total,
                spatial_exact=sum(r.get('spatial_exact', False) for r in eligible),
                spatial_denominator=sum('spatial_exact' in r for r in eligible),
                selected_source_tokens=sum(len(r['selection']['indices']) for r in eligible),
                target_source_tokens=sum(r.get('target_source_tokens', 0) for r in eligible),
                intersecting_source_tokens=sum(r.get('intersecting_source_tokens', 0) for r in eligible),
                seller_contamination_pages=sum(r.get('seller_contamination_tokens', 0)>0 for r in eligible),
                any_selection_in_ineligible=sum(bool(r['selection']['indices']) for r in rows if not r['eligible']))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['freeze', 'run'])
    p.add_argument('--root', type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    root = args.root.resolve()
    assert root.is_relative_to('/tmp')
    if args.action == 'freeze':
        root.mkdir(mode=0o700, exist_ok=False)
    rows, pins = inputs()
    if args.action == 'freeze':
        policy = {
            'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'files': pins,
            'cohort': 'Instance0 of each of 40 eligible TRAIN layouts; all 50 DEV invoices; all three '
                      'Synthesized DEV variants. Other 360 TRAIN invoices excluded by budget before inference. '
                      'No TEST/reserved members, new downloads or fitted weights.',
            'selection': 'Exactly one explicit recipient-label anchor. Labels and stops fixed in code. '
                         'Same-line suffix then at most six lines with normalized gaps [-0.25,2] median '
                         'line heights, overlap >=0.25 of narrower line or left alignment within two heights. '
                         'Nearest vertical continuation; competing branches within 0.5 heights conflict. '
                         'Multiple labels conflict. No label, empty adjacency, invalid geometry or cap -> null. '
                         'Never expected customer, annotated regions/text, issuer dictionaries or postal rules.',
            'grounding': 'Synthesized uses original word-array indices. FATURA cached OCR has only lines: '
                         'canonical whitespace tokens retain source line index, token offset, character span '
                         'and entire original line box. No invented word-level geometry. Report this limitation.',
            'ocr': 'Use fixed validated PP-OCR detail cache on DEV, same pinned reader/models on 40 TRAIN '
                   'pages, two workers, one RTen/Rayon thread, 30s/page timeout. Failures retained as null.',
            'metrics': 'FATURA eligible iff BILL_TO or BUYER annotation exists. Union of those regions; '
                       'source token centres determine target membership. Exact source-index set requires '
                       'nonempty target and selected output. Report selection/target/intersection counts, '
                       'seller-region contamination, null/conflict counts, and unchanged public_documents '
                       'token_score against recipient region text in y/x order. Ineligible pages retained '
                       'separately, not negatives. Synthesized has no region truth: text score only against '
                       'holder + street + city + state + full zip concatenation, no spatial score. No POA '
                       'acceptance, US validation, field correctness or integration improvement claim.',
            'no_tuning': 'One policy, one run, TRAIN and DEV separately reported; all failures retained.'}
        write(root / 'freeze.json', policy)
        print(json.dumps({'freeze_sha256': sha(root/'freeze.json'), 'fatura_pages':len(rows)}))
        return
    freeze = json.loads((root / 'freeze.json').read_text())
    assert freeze['files'] == pins
    assert not (root / 'report.json').exists()
    ocr_dir = root / 'train_ocr'
    ocr_dir.mkdir(mode=0o700, exist_ok=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        train = dict(pool.map(lambda r: train_ocr(r, ocr_dir), [r for r in rows if r['split']=='train']))
    results, raw = [], []
    for row in rows:
        truth = json.loads((DATA / 'fatura' / row['split'] / (row['id']+'.json')).read_text())
        output = train[row['id']] if row['split']=='train' else json.loads((CACHE/(row['id']+'.json')).read_text())
        failure = bool(output.get('error'))
        try:
            lines = REF.input_lines(output, truth['width'], truth['height'])
        except (ValueError, KeyError):
            lines, failure = [], True
        words = canonical_ocr_words(lines)
        selected = select(words, [truth['width'], truth['height']])
        if failure:
            selected = dict(status='ocr_error', indices=[])
        assert len(set(selected['indices'])) == len(selected['indices'])
        assert all(0 <= i < len(words) for i in selected['indices'])
        predicted = ' '.join(words[i]['text'] for i in selected['indices'])
        # Only after selection: annotations are referee inputs, never model inputs.
        fields = sorted([f for f in truth['fields'] if f['label'] in ('BILL_TO', 'BUYER')],
                        key=lambda f: (f['bbox'][1], f['bbox'][0]))
        target = {i for i,w in enumerate(words) if any(inside(w,f['bbox']) for f in fields)}
        sellers = [f for f in truth['fields'] if f['label'].startswith('SELLER')]
        result = dict(id=row['id'], split=row['split'], source='fatura', eligible=bool(fields),
                      ocr_failed=failure, selection=selected,
                      text_score=REF.token_score(' '.join(f['text'] for f in fields), predicted),
                      target_source_tokens=len(target),
                      intersecting_source_tokens=len(target & set(selected['indices'])),
                      spatial_exact=bool(target) and set(selected['indices']) == target and not failure,
                      seller_contamination_tokens=sum(any(inside(words[i],f['bbox']) for f in sellers)
                                                      for i in selected['indices']))
        results.append(result)
        raw.append(dict(id=row['id'], words=words, selection=selected, predicted=predicted))
    truth = json.loads((PUBLIC / 'truth.json').read_text())
    address = truth['address']
    target_text = ' '.join([truth['account_holder'], address['street'], address['city'], address['state'], address['zip']])
    for variant in PUBLIC_REF.VARIANTS:
        page = json.loads((PUBLIC/'baseline'/(variant+'.json')).read_text())['page']
        words = page['words']
        selected = select(words, page['page_size'])
        predicted = ' '.join(words[i]['text'] for i in selected['indices'])
        results.append(dict(id=variant, split='dev', source='synthesized', eligible=True, ocr_failed=bool(page.get('error')),
                            selection=selected, text_score=REF.token_score(target_text, predicted)))
        raw.append(dict(id=variant, words=words, selection=selected, predicted=predicted))
    assert inputs()[1] == pins
    report = dict(freeze=freeze, items=results, summary={
        'fatura_train': aggregate([r for r in results if r['source']=='fatura' and r['split']=='train']),
        'fatura_dev': aggregate([r for r in results if r['source']=='fatura' and r['split']=='dev']),
        'synthesized_dev': aggregate([r for r in results if r['source']=='synthesized'])},
        completed_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    write(root / 'raw.json', raw)
    write(root / 'report.json', report)
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
