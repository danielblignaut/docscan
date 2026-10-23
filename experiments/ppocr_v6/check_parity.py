"""Compare RTen0.26 and ONNX Runtime on tensors saved by evaluate.py."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import onnxruntime as ort
import yaml

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--models', type=Path, default=Path('/tmp/docscan-ppocr-v6'))
p.add_argument('--probe', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
args = p.parse_args()
rows = []
for tier in ('tiny', 'small'):
    for task in ('det', 'rec'):
        folder = args.models / f'{tier}_{task}'
        shape = json.loads((folder / 'real-input.json').read_text())
        source = folder / 'real-input.f32'
        target = folder / 'rten-output.f32'
        run = subprocess.run([str(args.probe), str(folder / 'inference.onnx'), str(source), ','.join(map(str, shape)), str(target)],
                             check=True, capture_output=True, text=True, timeout=120,
                             env={**os.environ, 'RTEN_NUM_THREADS': '2', 'RAYON_NUM_THREADS': '2'})
        meta = json.loads(run.stdout)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(folder / 'inference.onnx'), options, providers=['CPUExecutionProvider'])
        expected = session.run(None, {'x': np.fromfile(source, np.float32).reshape(shape)})[0]
        actual = np.fromfile(target, np.float32).reshape(meta['output_shape'])
        assert actual.shape == expected.shape
        difference = np.abs(actual - expected)
        row = {'model': f'{tier}_{task}', 'input_shape': shape, **meta,
               'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'max_abs_error': float(difference.max()), 'mean_abs_error': float(difference.mean()),
               'allclose_rtol1e-3_atol1e-4': bool(np.allclose(actual, expected, rtol=1e-3, atol=1e-4))}
        if task == 'det':
            threshold = yaml.safe_load((folder / 'inference.yml').read_text())['PostProcess']['thresh']
            row['threshold'] = threshold
            row['mask_pixels_different'] = int(np.count_nonzero((actual > threshold) != (expected > threshold)))
            row['mask_pixels_total'] = int(actual.size)
        if task == 'rec':
            row['ctc_argmax_equal'] = bool(np.array_equal(actual.argmax(axis=-1), expected.argmax(axis=-1)))
        rows.append(row)
        print(row, flush=True)
args.out.write_text(json.dumps({'runtime': 'RTen0.26 native versus ONNX Runtime CPU; not browser',
                                'source_sample': 'family1-size28-shade, max-side1754', 'rows': rows}, indent=2) + '\n')
