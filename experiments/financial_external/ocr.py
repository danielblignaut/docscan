#!/usr/bin/env python3
"""Run the pinned PP-OCRv6 tiny reader over every frozen page image, privately.

Pins the executable and model bytes in DATA/financial-external-v1/ocr/<key>/provenance.json before the first page,
runs at most two processes with one thread each, and refuses a run whose models changed. Failures are recorded,
never dropped: score.mjs passes them as failedPages and keeps their gold in the denominator.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = Path(os.environ.get('DOCSCAN_PUBLIC_DATA', '/tmp/docscan-public-data'))
ROOT = DATA / 'financial-external-v1'
MODELS = (REPO / 'models').resolve()
MODEL_NAMES = ['ppocr-v6-tiny-det.onnx', 'ppocr-v6-tiny-rec.onnx']


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def models_state():
    return {n: [digest(MODELS / n), (MODELS / n).stat().st_mtime_ns] for n in MODEL_NAMES}


def read(binary: Path, image: str):
    start = time.monotonic()
    try:
        result = subprocess.run([str(binary), f'--models={MODELS}', image], capture_output=True, text=True, timeout=180,
                                env={**os.environ, 'RTEN_NUM_THREADS': '1', 'RAYON_NUM_THREADS': '1'})
        if result.returncode:
            raise ValueError(f'exit {result.returncode}')
        lines = result.stdout.splitlines()
        if len(lines) != 1:
            raise ValueError('expected one JSON line')
        out = json.loads(lines[0])
        if out.get('model_directory') != str(MODELS):
            raise ValueError('reader did not confirm the model directory')
        if 'error' in out or not isinstance(out.get('lines'), list) or not isinstance(out.get('page_size'), list):
            raise ValueError('malformed output')
    except (ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        out = {'lines': [], 'text': '', 'error': type(error).__name__ + ': ' + str(error)[:120]}
    out['wall_ms'] = round((time.monotonic() - start) * 1000)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--sets', default='synthesized,bankstatemently,fatura_dev,fatura_train')
    args = p.parse_args()
    os.umask(0o077)
    freeze = json.loads((HERE / 'freeze.json').read_text())
    gold = ROOT / 'gold.json'
    if digest(gold) != freeze['gold_sha256']:
        raise ValueError('gold.json differs from freeze')
    docs = [d for d in json.loads(gold.read_text())['documents'] if d['set'] in args.sets.split(',')]
    provenance = {'binary_sha256': digest(args.binary), 'models': {k: v[0] for k, v in models_state().items()},
                  'engine': 'ppocr_v6_tiny', 'detail': False, 'ocr_script_sha256': digest(Path(__file__)),
                  'gold_sha256': freeze['gold_sha256']}
    key = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:16]
    out_dir = ROOT / 'ocr' / key
    out_dir.mkdir(parents=True, exist_ok=True)
    frozen_binary = out_dir / 'text_v6'
    if not frozen_binary.exists():
        shutil.copy2(args.binary, frozen_binary)
    if digest(frozen_binary) != provenance['binary_sha256']:
        raise ValueError('binary changed during snapshot')
    (out_dir / 'provenance.json').write_text(json.dumps(provenance, indent=1) + '\n')
    before = models_state()
    jobs = [(d['id'], i, img) for d in docs for i, img in enumerate(d['images'])]
    jobs = [j for j in jobs if not (out_dir / f'{j[0]}.p{j[1]}.json').exists()]

    def run(job):
        ident, index, image = job
        out = read(frozen_binary, image)
        out['image_sha256'] = digest(Path(image))
        (out_dir / f'{ident}.p{index}.json').write_text(json.dumps(out, ensure_ascii=False) + '\n')
        return 'error' in out

    with ThreadPoolExecutor(max_workers=2) as pool:
        failures = sum(pool.map(run, jobs))
    if models_state() != before:
        raise RuntimeError('models changed during OCR; discard this run')
    (out_dir / 'complete.json').write_text(json.dumps({'pages_run': len(jobs), 'failures_this_run': failures,
                                                      **provenance}, indent=1) + '\n')
    print(json.dumps({'key': key, 'pages_run': len(jobs), 'failures': failures}))


if __name__ == '__main__':
    main()
