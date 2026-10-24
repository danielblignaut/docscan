#!/usr/bin/env python3
"""Byte parity of exposure.rs: Python reference vs native vs wasm32 (Node).

Inputs: every frozen baseline input of the optics DEV run (as evaluate.py) and
fixed synthetic edge shapes (1x1, thin strips, OpenCV's integer fast path,
fractional factors, ties in the thumbnail size, bright and dark). Each runs as
RGB and, in wasm, also as RGBA with a patterned alpha that must come back
untouched. No inference, no timing. Raw frames stay in a private directory.
"""
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO/'experiments/research_optics'))
from optics import preprocess  # noqa: E402
from run import sha, write  # noqa: E402


def synthetic():
    rng = np.random.default_rng(5150)
    shapes = [(1, 1), (1, 900), (900, 1), (10, 513), (701, 1024), (1024, 1024), (1536, 2048),
              (2048, 1536), (513, 513), (511, 600), (1023, 3), (512, 512), (1684, 1191), (1920, 1080),
              (1024, 768), (768, 1024), (1024, 6), (1000, 1024), (1536, 1536), (1536, 1152), (2560, 1920), (1280, 720)]
    for i, (h, w) in enumerate(shapes):
        for level, name in ((40, 'dark'), (200, 'bright')):
            base = rng.normal(level, 25, (h, w, 3))
            base[h//3:h//3+max(1, h//20), :] = 5
            yield f'synthetic-{i:02d}-{h}x{w}-{name}', np.clip(base, 0, 255).astype(np.uint8)
    # A level placed near the gate, where float differences would show first.
    for v in (186, 187, 188, 189):
        yield f'synthetic-gate-{v}', np.full((300, 400, 3), v, np.uint8)


def frozen_inputs(results):
    report = json.loads(Path(results).read_text())
    run = Path(report['private_run'])
    assert sha(run/'freeze.json') == report['freeze_sha256']
    frozen = json.loads((run/'freeze.json').read_text())
    for group in ('documents', 'camera', 'negatives'):
        for e in frozen[group]:
            if e['arm'] == 'baseline':
                entry = frozen['unique_inputs'][e['key']]
                assert sha(entry['path']) == entry['sha256']
                yield e['key'], np.asarray(Image.open(entry['path']).convert('RGB'))


def raw(path, rgb):
    h, w = rgb.shape[:2]
    path.write_bytes(np.uint32(w).tobytes()+np.uint32(h).tobytes()+rgb.tobytes())


def load(path, shape):
    if not path.exists():
        return None
    return np.frombuffer(path.read_bytes()[8:], np.uint8).reshape(shape)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--wasm', type=Path, required=True)
    p.add_argument('--results', type=Path, default=REPO/'experiments/research_optics/results-v1.json')
    p.add_argument('--output', type=Path, default=HERE/'wasm-parity-v1.json')
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('refusing overwrite')
    os.umask(0o077)
    root = Path('/tmp/docscan-research-optics-native')
    root.mkdir(mode=0o700, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='wasm-parity-', dir=root))
    items = {}
    for name, rgb in [*frozen_inputs(a.results), *synthetic()]:
        if name in items:
            continue
        items[name] = rgb
        raw(work/f'{name}.raw', rgb)
    wasm = {}
    lines = subprocess.run(['node', str(HERE/'wasm/run.mjs'), str(a.wasm), str(work)],
                           capture_output=True, text=True, check=True, timeout=1800).stdout.splitlines()
    for line in lines:
        r = json.loads(line)
        wasm[r['name'][:-4], r['rgba']] = r
    rows = []
    for name, rgb in items.items():
        ref, meta = preprocess(rgb, 'global_exposure')
        nat = json.loads(subprocess.run([str(a.binary), 'apply', str(work/f'{name}.raw'), str(work/f'{name}.native-out')],
                                        capture_output=True, text=True, check=True).stdout)
        native = load(work/f'{name}.native-out', rgb.shape)
        native = rgb if native is None else native
        row = {'item': name if name.startswith('synthetic') else 'frozen-dev-input', 'shape': list(rgb.shape),
               'python_p90': meta['background_p90'], 'native_p90': nat['background_p90'],
               'python_changed': meta['changed'], 'native_changed': nat['changed'],
               'native_equals_python': bool(np.array_equal(native, ref))}
        for rgba in (False, True):
            w = wasm[name, rgba]
            out = load(work/f'{name}.{"wasm-rgba-out" if rgba else "wasm-out"}', rgb.shape)
            out = rgb if out is None else out
            tag = 'wasm_rgba' if rgba else 'wasm_rgb'
            row[f'{tag}_equals_native'] = bool(np.array_equal(out, native))
            row[f'{tag}_p90_bits_equal_native'] = w['p90'] == nat['background_p90']
            row[f'{tag}_gain_bits_equal_native'] = w['gain'] == nat['gain']
            row[f'{tag}_alpha_kept'] = w['alpha_kept']
        rows.append(row)
    checks = [k for k in rows[0] if k.endswith(('_equals_native', '_equals_python', '_bits_equal_native', '_alpha_kept'))]
    summary = {'items': len(rows), 'frozen_dev_inputs': sum(r['item'] == 'frozen-dev-input' for r in rows),
               'synthetic': sum(r['item'] != 'frozen-dev-input' for r in rows),
               'applied': sum(r['native_p90'] < .55 for r in rows),
               **{k: sum(r[k] for r in rows) for k in checks},
               'max_p90_abs_diff_native_python': max(abs(r['native_p90']-r['python_p90']) for r in rows)}
    result = {'version': 'exposure-wasm-parity-v1', 'utc': datetime.now(timezone.utc).isoformat(),
              'exposure_rs_sha256': sha(REPO/'docscan/src/exposure.rs'), 'binary_sha256': sha(a.binary),
              'wasm_sha256': sha(a.wasm), 'node': subprocess.run(['node', '--version'], capture_output=True, text=True).stdout.strip(),
              'private_work': str(work), 'summary': summary,
              'synthetic_rows': [r for r in rows if r['item'] != 'frozen-dev-input'],
              'limits': 'Node V8 wasm32, not a phone browser; the parent wasm-bindgen build is a different binary and must be checked by its own browser test.'}
    write(a.output, result)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
