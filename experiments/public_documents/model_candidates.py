#!/usr/bin/env python3
"""Predeclared native model/resolution ablation; not a browser or shipped change.

Uses the same frozen external DEV images and scorer as evaluate.py. Runs ALL
four configurations, never reserved data, without selecting a threshold.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
from collections import defaultdict
import time
import evaluate as referee

MODES = [('tiny', 960), ('tiny', 1600), ('small', 960), ('small', 1600)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', type=Path, default=Path('/tmp/docscan-ppocr-v6'))
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    module_path = referee.REPO / 'experiments/ppocr_v6/evaluate.py'
    spec = importlib.util.spec_from_file_location('paddle_reference', module_path)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    samples, frozen = referee.materialize()
    if frozen != json.loads((referee.HERE / 'ocr-dev-v1.json').read_text()):
        raise ValueError('DEV data differs from frozen manifest')
    model_provenance = json.loads((args.models / 'provenance.json').read_text())
    for tier in ('tiny', 'small'):
        for task in ('det', 'rec'):
            for name, record in model_provenance[f'{tier}_{task}']['files'].items():
                if referee.digest(args.models / f'{tier}_{task}' / name) != record['sha256']:
                    raise ValueError('Model does not match acquisition hashes')
    raw_root = referee.DATA / 'document-model-candidates-v1'
    raw_root.mkdir(exist_ok=True)
    report = {'protocol': 'public-document-model-ablation-v1',
              'modes': MODES, 'scorer_sha256': referee.digest(referee.__file__),
              'runner_sha256': referee.digest(__file__),
              'reference_pipeline_sha256': referee.digest(module_path),
              'manifest_sha256': referee.digest(referee.HERE / 'ocr-dev-v1.json'),
              'models': model_provenance, 'results': {},
              'limitations': 'DEV only; native ONNX Runtime/Python geometry, not Rust/browser parity. '
              'All four predeclared modes reported; no trained weights, no phone timing or SOTA claim.'}
    for tier, limit in MODES:
        mode = f'{tier}-max{limit}'
        pipeline = reference.Pipeline(args.models, tier, 1)
        groups = defaultdict(list)
        failures = 0
        rows = []
        for sample in samples:
            image = reference.cv2.imread(sample['path'])
            start = time.monotonic()
            try:
                boxes = pipeline.detect(image, limit)
                lines = []
                for box in boxes:
                    text = pipeline.recognize(reference.crop(image, box))
                    x, y = box.min(axis=0).tolist()
                    right, bottom = box.max(axis=0).tolist()
                    lines.append({'text': text, 'x': x, 'y': y, 'w': right-x, 'h': bottom-y})
                output = {'text': '\n'.join(line['text'] for line in lines), 'lines': lines}
            except Exception as error:
                failures += 1
                output = {'text': '', 'lines': [], 'error': type(error).__name__}
            (raw_root / f'{mode}-{sample["id"]}.json').write_text(json.dumps(output, ensure_ascii=False)+'\n')
            scores = []
            if sample['source'] == 'bankstatemently':
                scores.append({'label': 'full_page', **referee.token_score(sample['text'], output['text'])})
            else:
                for field in sample['fields']:
                    scores.append({'label': field['label'], **referee.token_score(field['text'], referee.region_text(output['lines'], field['bbox']))})
            for score in scores:
                groups[sample['source']].append(score)
                groups[sample['source']+'.'+score['label']].append(score)
            rows.append({'id': sample['id'], 'source': sample['source'], 'failed': 'error' in output, 'scores': scores})
            print(mode, sample['id'], round(time.monotonic()-start, 2), flush=True)
        report['results'][mode] = {'summary': {k: referee.summary(v) for k,v in sorted(groups.items())}, 'failed_pages': failures, 'rows': rows}
        args.report.parent.mkdir(exist_ok=True, parents=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n')
        print(mode, {k:v for k,v in report['results'][mode]['summary'].items() if '.' not in k}, flush=True)


if __name__ == '__main__':
    main()
