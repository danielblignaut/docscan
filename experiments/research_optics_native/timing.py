#!/usr/bin/env python3
"""In-process cost of exposure.rs (native release) beside the frozen Python arm.

Descriptive only, and only of the preprocessing call: the 8 dark DEV pages the
frozen optics timing used (one per statement/layout, gate open) and the 18
camera frames (mostly gate shut). Pixels are loaded before any timer; the Rust
binary times `correct()` in-process after one warm-up, so process start-up,
file I/O and PNG coding are excluded from both arms. One pinned CPU, arms
alternated per item and repeat. It is not the OCR pass the alternative reading
adds (that second PP-OCR read dominates; see the frozen timing-v1.json), and
it is not browser, WASM or phone latency.
"""
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO/'experiments/research_optics'))
from optics import preprocess  # noqa: E402
from run import sha, write  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--results', type=Path, default=REPO/'experiments/research_optics/results-v1.json')
    p.add_argument('--output', type=Path, default=HERE/'timing-native-v1.json')
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--calls', type=int, default=20)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('refusing overwrite')
    os.umask(0o077)
    report = json.loads(a.results.read_text())
    run = Path(report['private_run'])
    assert sha(run/'freeze.json') == report['freeze_sha256']
    frozen = json.loads((run/'freeze.json').read_text())
    timing = json.loads((REPO/'experiments/research_optics/timing-v1.json').read_text())
    selected = timing['receipt']['sample_indices']
    items = [('dark-page', e) for e in frozen['documents']
             if e['arm'] == 'baseline' and e['condition'] == 'dark' and e['index'] in selected]
    items += [('camera-frame', e) for e in frozen['camera'] if e['arm'] == 'baseline']
    cpu = sorted(os.sched_getaffinity(0))[-1]
    os.sched_setaffinity(0, {cpu})
    root = Path('/tmp/docscan-research-optics-native')
    root.mkdir(mode=0o700, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='timing-', dir=root))
    data = []
    for kind, e in items:
        entry = frozen['unique_inputs'][e['key']]
        assert sha(entry['path']) == entry['sha256']
        rgb = np.asarray(Image.open(entry['path']).convert('RGB'))
        path = work/f"{len(data)}.raw"
        path.write_bytes(np.uint32(rgb.shape[1]).tobytes()+np.uint32(rgb.shape[0]).tobytes()+rgb.tobytes())
        data.append((kind, rgb, path))
    load_before = os.getloadavg()
    rows = []
    for repeat in range(a.repeats):
        for i, (kind, rgb, path) in enumerate(data):
            order = ['python', 'native'] if (i+repeat) % 2 else ['native', 'python']
            row = {'item': i, 'kind': kind, 'repeat': repeat, 'megapixels': rgb.shape[0]*rgb.shape[1]/1e6}
            for arm in order:
                if arm == 'python':
                    preprocess(rgb, 'global_exposure')
                    ms = []
                    for _ in range(a.calls):
                        start = time.perf_counter()
                        _, meta = preprocess(rgb, 'global_exposure')
                        ms.append((time.perf_counter()-start)*1000)
                    row['python_applied'] = bool(meta.get('background_p90', 1) < .55)
                else:
                    out = json.loads(subprocess.run([str(a.binary), 'time', str(path), str(a.calls)],
                                                    capture_output=True, text=True, check=True).stdout)
                    ms = [n/1e6 for n in out['ns']]
                    row['native_applied'] = out['applied']
                row[f'{arm}_median_ms'] = float(np.median(ms))
            rows.append(row)
        print(json.dumps({'repeat_completed': repeat+1}), flush=True)
    summary = {}
    for kind in ('dark-page', 'camera-frame'):
        part = [r for r in rows if r['kind'] == kind]
        summary[kind] = {'items': len({r['item'] for r in part}), 'runs': len(part),
                         'applied': sum(r['native_applied'] for r in part if r['repeat'] == 0),
                         'megapixels': sorted({r['megapixels'] for r in part}),
                         'native_median_ms': float(np.median([r['native_median_ms'] for r in part])),
                         'native_max_ms': float(np.max([r['native_median_ms'] for r in part])),
                         'python_median_ms': float(np.median([r['python_median_ms'] for r in part])),
                         'native_ms_per_megapixel': float(np.median([r['native_median_ms']/r['megapixels'] for r in part])),
                         'median_native_over_python': float(np.median([r['native_median_ms']/r['python_median_ms'] for r in part]))}
    result = {'version': 'exposure-native-timing-v1', 'utc': datetime.now(timezone.utc).isoformat(),
              'exposure_rs_sha256': sha(REPO/'docscan/src/exposure.rs'), 'binary_sha256': sha(a.binary),
              'cpu': cpu, 'load_before': load_before, 'load_after': os.getloadavg(),
              'repeats': a.repeats, 'calls_per_measurement': a.calls, 'summary': summary, 'rows': rows,
              'frozen_python_ocr_pass_median_ms': timing['summary']['global_exposure']['baseline_median_ms'],
              'limits': __doc__.split('\n\n', 1)[1].strip()}
    write(a.output, result)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
