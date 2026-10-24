#!/usr/bin/env python3
"""Frozen external-document OCR referee. Source media/text stay outside git."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import unicodedata

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = Path(os.environ.get('DOCSCAN_PUBLIC_DATA', '/tmp/docscan-public-data'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normal(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def tokens(text):
    # Punctuation remains meaningful in dates, amounts and account numbers.
    return Counter(normal(text).split())


def token_score(truth, actual):
    a, b = tokens(truth), tokens(actual)
    hit = sum((a & b).values())
    return {'truth_tokens': sum(a.values()), 'predicted_tokens': sum(b.values()),
            'matched_tokens': hit, 'exact': normal(truth) == normal(actual)}


def input_lines(output, width, height):
    # OCRS returns its working-page coordinates, PP-OCR original-input ones.
    ow, oh = output.get('page_size', [width, height])
    if ow <= 0 or oh <= 0:
        raise ValueError('Invalid OCR page size')
    if output.get('error'):
        return []
    if output.get('engine') == 'ppocr_v6_tiny':
        expected = (width, height)
    else:
        scale = min(1754 / max(width, height), 2)
        if abs(scale - 1) <= .02:
            scale = 1
        expected = (round(width * scale), round(height * scale))
    # OCRS deskew expands its canvas. Until it publishes the inverse transform,
    # do not silently score rotated coordinates using a scale-only mapping.
    if abs(ow - expected[0]) > 1 or abs(oh - expected[1]) > 1:
        raise ValueError('Unsupported deskew geometry: spatial scoring requires an inverse transform')
    return [{**line, 'x': line['x'] * width / ow, 'w': line['w'] * width / ow,
             'y': line['y'] * height / oh, 'h': line['h'] * height / oh}
            for line in output['lines']]


def region_text(lines, box):
    # Predicted line centres select annotation regions. No annotation-guided OCR.
    x0, y0, x1, y1 = box
    found = [line for line in lines
             if x0 <= line['x'] + line['w'] / 2 <= x1
             and y0 <= line['y'] + line['h'] / 2 <= y1]
    return '\n'.join(line['text'] for line in sorted(found, key=lambda r: (r['y'], r['x'])))


def summary(rows):
    total = {key: sum(r[key] for r in rows) for key in
             ('truth_tokens', 'predicted_tokens', 'matched_tokens')}
    total.update(items=len(rows), exact=sum(r['exact'] for r in rows))
    total['token_recall'] = total['matched_tokens'] / max(1, total['truth_tokens'])
    total['token_precision'] = total['matched_tokens'] / max(1, total['predicted_tokens'])
    return total


def materialize():
    import pypdfium2 as pdfium
    protocol = json.loads((HERE / 'protocol.json').read_text())
    source_manifest = json.loads((HERE / 'manifest.json').read_text())
    samples = []
    # Every DEV layout/instance is predeclared; no cherry-picked pages.
    for row in source_manifest['fatura']['documents']:
        if row['split'] != 'dev':
            continue
        folder = DATA / 'fatura' / 'dev'
        path = folder / (row['id'] + '.jpg')
        if digest(path) != row['image_sha256']:
            raise ValueError('FATURA image differs from pinned acquisition')
        truth = json.loads((folder / (row['id'] + '.json')).read_text())
        samples.append({'id': row['id'], 'source': 'fatura', 'path': str(path),
                        'fields': truth['fields'], 'width': truth['width'], 'height': truth['height'], 'image_sha256': digest(path),
                        'truth_sha256': digest(folder / (row['id'] + '.json'))})
    render = DATA / 'bankstatemently' / 'rendered-dev-v1'
    render.mkdir(exist_ok=True)
    bank_rows = {r['path']: r for r in source_manifest['bankstatemently']['files']}
    for identity in protocol['bankstatemently']['dev']:
        relative = f'datasets/basic/{identity}/{identity}-statement.pdf'
        pdf = DATA / 'bankstatemently' / relative
        if digest(pdf) != bank_rows[relative]['sha256']:
            raise ValueError('PDF differs from pinned acquisition')
        with pdfium.PdfDocument(pdf) as doc:
            for i in range(len(doc)):
                page = doc[i]
                # Fixed 144 dpi; all pages, including near-blank final pages.
                path = render / f'{identity}-p{i+1}.png'
                page.render(scale=2).to_pil().convert('RGB').save(path)
                text = page.get_textpage().get_text_range()
                if not normal(text):
                    raise ValueError('No PDF text layer; requires independent transcription')
                samples.append({'id': f'{identity}-p{i+1}', 'source': 'bankstatemently',
                                'path': str(path), 'text': text, 'image_sha256': digest(path),
                                'truth_sha256': hashlib.sha256(text.encode()).hexdigest()})
    frozen = {'version': 'public-document-ocr-dev-v1', 'source_manifest_sha256': digest(HERE / 'manifest.json'),
              'protocol_sha256': digest(HERE / 'protocol.json'), 'bank_render_dpi': 144,
              'samples': [{k: row[k] for k in ('id', 'source', 'image_sha256', 'truth_sha256')} for row in samples]}
    return samples, frozen


def infer(sample, binary, engine, cache, detail=False):
    out = cache / (sample['id'] + '.json')
    if out.exists():
        return json.loads(out.read_text())
    args = [str(binary)]
    args.append('--models=' + str((REPO / 'models').resolve()))
    if detail:
        args.append('--detail')
    args.append(sample['path'])
    start = time.monotonic()
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=180,
                                env={**os.environ, 'RTEN_NUM_THREADS': '1', 'RAYON_NUM_THREADS': '1'})
        if result.returncode:
            raise ValueError('OCR process failed: ' + str(result.returncode))
        lines = result.stdout.splitlines()
        if len(lines) != 1:
            raise ValueError('Expected exactly one OCR result')
        prediction = json.loads(lines[0])
        if prediction.get('model_directory') != str((REPO / 'models').resolve()):
            raise RuntimeError('Reader did not confirm the pinned model directory; rebuild its current CLI')
        if 'error' in prediction:
            raise ValueError(prediction['error'])
        if not isinstance(prediction.get('text'), str) or not isinstance(prediction.get('lines'), list):
            raise ValueError('Malformed OCR output')
    except (ValueError, subprocess.TimeoutExpired) as error:
        prediction = {'text': '', 'lines': [], 'error': type(error).__name__}
    prediction['wall_ms'] = (time.monotonic() - start) * 1000
    out.write_text(json.dumps(prediction, ensure_ascii=False) + '\n')
    return prediction


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--freeze', action='store_true', help='Create the manifest once, before evaluating')
    p.add_argument('--binary', type=Path)
    p.add_argument('--engine', choices=['ppocr_v6_tiny', 'ocrs_page'])
    p.add_argument('--report', type=Path)
    p.add_argument('--detail', action='store_true', help='Use the optional PP-OCR small-print profile')
    args = p.parse_args()
    os.umask(0o077)
    samples, frozen = materialize()
    manifest = HERE / 'ocr-dev-v1.json'
    if args.freeze:
        if manifest.exists():
            raise ValueError('Refusing to overwrite frozen manifest; deliberately version a new protocol')
        manifest.write_text(json.dumps(frozen, indent=2) + '\n')
        print(json.dumps({'frozen': len(samples)}))
        return
    if json.loads(manifest.read_text()) != frozen:
        raise ValueError('Evaluation data changed from frozen manifest')
    if not args.binary or not args.engine or not args.report:
        p.error('--binary, --engine and --report required for evaluation')
    if args.detail and args.engine != 'ppocr_v6_tiny':
        p.error('--detail requires ppocr_v6_tiny')
    binary = args.binary.resolve()
    model_names = (['ppocr-v6-tiny-det.onnx', 'ppocr-v6-tiny-rec.onnx'] if args.engine == 'ppocr_v6_tiny'
                   else ['text-detection.rten', 'text-recognition.rten', 'text-detection-page.onnx'])
    provenance = {'binary_sha256': digest(binary), 'engine': args.engine, 'detail': args.detail,
                  'models': {name: digest(REPO / 'models' / name) for name in model_names},
                  'scorer_sha256': digest(__file__), 'manifest_sha256': digest(manifest)}
    key = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    cache = DATA / 'document-ocr-cache' / key
    cache.mkdir(parents=True, exist_ok=True)
    # Snapshot executable so a concurrent build cannot mix versions mid-run.
    frozen_binary = cache / 'reader'
    if not frozen_binary.exists():
        shutil.copy2(binary, frozen_binary)
    if digest(frozen_binary) != provenance['binary_sha256']:
        raise ValueError('Executable changed during snapshot')
    groups = defaultdict(list)
    rows = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = pool.map(lambda sample: infer(sample, frozen_binary, args.engine, cache, args.detail), samples)
        for sample, output in zip(samples, outputs):
            entry = {'id': sample['id'], 'source': sample['source'], 'failed': 'error' in output}
            scored = []
            if sample['source'] == 'bankstatemently':
                scored.append({'label': 'full_page', **token_score(sample['text'], output['text'])})
            else:
                lines = input_lines(output, sample['width'], sample['height'])
                for field in sample['fields']:
                    scored.append({'label': field['label'], **token_score(field['text'], region_text(lines, field['bbox']))})
            for score in scored:
                groups[sample['source']].append(score)
                groups[sample['source'] + '.' + score['label']].append(score)
            entry['scores'] = scored
            rows.append(entry)
            print(sample['id'], 'failed' if entry['failed'] else 'scored', flush=True)
    if {name: digest(REPO / 'models' / name) for name in model_names} != provenance['models']:
        raise RuntimeError('Models changed during evaluation')
    report = {'protocol': frozen['version'], 'provenance': provenance,
              'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
              'summary': {name: summary(values) for name, values in sorted(groups.items())},
              'failed_pages': sum(row['failed'] for row in rows), 'pages': len(rows), 'rows': rows,
              'limitations': 'DEV only; synthetic PDFs/invoices. Bank reference is PDF text-layer, not official transaction truth. '
              'FATURA scores text inside annotated regions, not predicted field labels or POA verification. '
              'No complete-page hallucination metric on FATURA. Template/page correlated; no SOTA or latency claim.'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report['summary'].items() if '.' not in k}, indent=2))


if __name__ == '__main__':
    main()
