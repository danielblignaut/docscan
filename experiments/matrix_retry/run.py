#!/usr/bin/env python3
"""All pinned DEV rows, unchanged scorer, native bounded retry candidates.

Raw results are owner-only in /tmp. Export includes opaque IDs and aggregates,
never images, file names, payloads or decoder stderr. No TEST is enumerated.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image
import numpy as np
from prepare import ROOT, HERE, WORK, sha

sys.path.insert(0, str(WORK/'before/bench'))
from lib.common import safe_digest
from lib.stats import paired_latency_ratio
from suites.barcode import score
from compare import compare_rate

DATA = Path('/tmp/docscan-bench')
MODES = ['baseline', 'matrix_both', 'empty_half']
ENV = {**os.environ, 'RAYON_NUM_THREADS':'1', 'RTEN_NUM_THREADS':'1'}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def opaque(value):
    return hashlib.sha256(value.encode()).hexdigest()


def datasets():
    config = json.loads((WORK/'protocol.json').read_text())
    assert config['split'] == 'dev'
    loaded = {}
    for name, expected in config['datasets'].items():
        assert name in ['barcode_public_dev', 'barcode_synth_dev']
        manifest = json.loads((WORK/'before/bench/manifests'/f'{name}.json').read_text())
        assert manifest.get('split','dev') == 'dev'
        root = DATA/manifest['root']
        for f in manifest['files']:
            p = root/f['path']
            assert p.stat().st_size == f['bytes'] and safe_digest(sha(p)) == f['sha256'], f['path']
        rows = [json.loads(line) for line in (root/'truth.jsonl').read_text().splitlines() if line.strip()]
        assert len(rows) == expected
        for i, row in enumerate(rows):
            row['id'] = f'{name}:{i}'
            row['path'] = str(root/row['image'])
        loaded[name] = rows
    assert sum(map(len, loaded.values())) == 577
    return loaded


def verify_receipt():
    receipt = json.loads((WORK/'source-receipt.json').read_text())
    if (WORK/'frozen.json').exists():
        assert sha(WORK/'source-receipt.json') == json.loads((WORK/'frozen.json').read_text())['source_receipt_sha256']
    for name, digest in receipt.items():
        assert sha(WORK/name) == digest, name
    for name in ['protocol.json','probe.rs','run.py','prepare.py']:
        if (WORK/'frozen.json').exists():
            assert sha(WORK/'experiment-source'/name) == json.loads((WORK/'frozen.json').read_text())['experiment_files'][name]
    if (WORK/'frozen.json').exists():
        for name, digest in json.loads((WORK/'frozen.json').read_text())['binaries'].items():
            assert sha(WORK/'bin'/name) == digest


def invoke(mode, path, cpu=None):
    binary = WORK/'bin'/('before' if mode=='baseline' else 'after')
    command = [str(binary), mode, path]
    if cpu is not None:
        command = ['taskset','-c',str(cpu),*command]
    status = {'timeout':False, 'crash':False, 'error':False}
    start = time.monotonic()
    try:
        p = subprocess.run(command, capture_output=True, text=True, timeout=30, env=ENV)
        if p.returncode:
            result = {'barcodes':[]}
            status['crash'] = True
        else:
            result = json.loads(p.stdout)
    except subprocess.TimeoutExpired:
        result = {'barcodes':[]}
        status['timeout'] = True
    except (ValueError, IndexError):
        result = {'barcodes':[]}
        status['error'] = True
    return {**result, **status, 'wall_ms':(time.monotonic()-start)*1000}


def private_path(name, i):
    return WORK/'private'/name/f'{i}.json'


def accuracy():
    verify_receipt()
    loaded = datasets()
    frozen = WORK/'frozen.json'
    if frozen.exists():
        raise FileExistsError('Frozen trial exists. Retain it; do not overwrite.')
    (WORK/'experiment-source').mkdir(exist_ok=False)
    for name in ['protocol.json','probe.rs','run.py','prepare.py']:
        shutil.copy2(HERE/name, WORK/'experiment-source'/name)
    write(frozen, {
        'utc':datetime.now(timezone.utc).isoformat(),
        'protocol':json.loads((WORK/'protocol.json').read_text()),
        'source_receipt_sha256':sha(WORK/'source-receipt.json'),
        'experiment_files':{n:sha(HERE/n) for n in ['protocol.json','probe.rs','run.py','prepare.py']},
        'binaries':{n:sha(WORK/'bin'/n) for n in ['before','after']},
        'rustc':subprocess.check_output(['/home/dan/.cargo/bin/rustc','-Vv'],text=True),
        'build':'cargo build --locked --release --example matrix_probe -j2; CARGO_TARGET_DIR=/tmp/docscan-matrix-retry-v1/target',
        'manifests':{name:sha(WORK/'before/bench/manifests'/f'{name}.json') for name in loaded},
        'scorers':{name:sha(WORK/'before/bench'/name) for name in ['suites/barcode.py','lib/common.py','lib/stats.py','compare.py','noise.json']},
        'env':{k:ENV[k] for k in ['RAYON_NUM_THREADS','RTEN_NUM_THREADS']},
    })
    for name, rows in loaded.items():
        def trial(pair):
            i, row = pair
            with Image.open(row['path']) as image:
                w,h = image.size
            # Order balanced across frames; timing verdict is separate below.
            modes = MODES if i%2==0 else MODES[::-1]
            results = {mode:invoke(mode,row['path']) for mode in modes}
            first = results['baseline']
            valid = w>=16 and h>=16
            passes = {'baseline':1, 'matrix_both':int(valid)*(2+int(w>=32 and h>=32)),
                      'empty_half':int(valid)*(1+int(not first['barcodes'] and w>=32 and h>=32))}
            write(private_path(name,i), {'input_sha256':sha(row['path']), 'dimensions':[w,h], 'variants':results, 'read_all_passes':passes})
            if i%25==0:
                print(name,i,'complete',flush=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(trial, enumerate(rows)))
    summarize(loaded)
    verify_receipt()


def changed_ids(a, b):
    # Shared m_rate stores outcomes as a compact string, not booleans.
    return {
        'new_true_ids':[opaque(i) for i,x,y in zip(b['ids'],a['ok'],b['ok']) if int(y) and not int(x)],
        'lost_true_ids':[opaque(i) for i,x,y in zip(b['ids'],a['ok'],b['ok']) if int(x) and not int(y)],
    }


def summarize(loaded):
    output = {'provenance':json.loads((WORK/'frozen.json').read_text()), 'datasets':{}}
    for name, rows in loaded.items():
        trials = [json.loads(private_path(name,i).read_text()) for i in range(len(rows))]
        scored = {mode:score(name,rows,{r['path']:t['variants'][mode] for r,t in zip(rows,trials)}) for mode in MODES}
        output['datasets'][name] = {}
        for mode in MODES:
            comparisons = {}
            for key, m in scored[mode].items():
                if m['kind']!='rate':
                    continue
                a = scored['baseline'][key]
                d, lo, hi, how = compare_rate(a,m)
                comparisons[key] = {'delta':d, 'ci95':[lo,hi], 'comparison':how}
                if a['ids']==m['ids']:
                    comparisons[key].update(changed_ids(a,m))
            lost_objects = []
            errors = []
            for row, t in zip(rows,trials):
                a = t['variants']['baseline']; b = t['variants'][mode]
                if any(obj not in b['barcodes'] for obj in a['barcodes']):
                    lost_objects.append(opaque(row['id']))
                if b['error']:
                    errors.append(opaque(row['id']))
            redacted = json.loads(json.dumps(scored[mode]))
            for metric in redacted.values():
                if 'ids' in metric:
                    metric['ids'] = [opaque(i) for i in metric['ids']]
            output['datasets'][name][mode] = {
                'metrics':redacted, 'comparisons':comparisons, 'lost_baseline_object_frame_ids':lost_objects, 'error_frame_ids':errors,
                'read_all_passes':sum(t['read_all_passes'][mode] for t in trials),
                'pass_accounting':'exact from deterministic baseline outputs on completed calls; upper bound for timeout/crash; each read_all includes its existing internal detector passes',
                'total_process_wall_seconds':sum(t['variants'][mode]['wall_ms'] for t in trials)/1000,
                'items':[{'id':opaque(r['id']), 'input_sha256':t['input_sha256'], 'passes':t['read_all_passes'][mode], **{k:t['variants'][mode].get(k) for k in ['ms','wall_ms','timeout','crash','error']}} for r,t in zip(rows,trials)]
            }
            print(name,mode,{k:(redacted[f'barcode.{name}.{k}']['k'],redacted[f'barcode.{name}.{k}']['n']) for k in ['recall','false_decode_frames','timeouts','crashes']},flush=True)
    write(WORK/'accuracy.json',output)


def latency():
    verify_receipt()
    loaded = datasets()
    dest = WORK/'latency.json'
    if dest.exists() or (WORK/'latency-start.json').exists():
        raise FileExistsError('Timing trial already started; never overwrite.')
    cpu = min(os.sched_getaffinity(0))
    result = {'cpu':cpu,'load_start':list(os.getloadavg()),'repeats':4,'selection':'predeclared stride, independent of outcomes','metrics':{},'pairs':[]}
    write(WORK/'latency-start.json',{'utc':datetime.now(timezone.utc).isoformat(),'cpu':cpu})
    for name, rows in loaded.items():
        selected = [r for r in rows if not r.get('negative')][::max(1,len(rows)//20)][:20]
        for variant in MODES[1:]:
            pairs = []
            for repeat in range(4):
                for row in selected:
                    order = ['baseline',variant] if repeat%2==0 else [variant,'baseline']
                    measured = {mode:invoke(mode,row['path'],cpu) for mode in order}
                    pairs.append({'id':opaque(row['id']), 'repeat':repeat, 'variant':variant, 'dataset':name,
                                  'times':{mode:{k:v.get(k) for k in ['ms','wall_ms','timeout','crash','error']} for mode,v in measured.items()}})
                print('timing',name,variant,repeat+1,'of 4',flush=True)
                write(WORK/'latency-progress.json',{'pairs':result['pairs']+pairs})
            result['pairs'].extend(pairs)
            summary = {}
            for field in ['ms','wall_ms']:
                # Failed attempts receive full budget, never silently disappear.
                values = [[p['times'][side][field] if not any(p['times'][side][k] for k in ['timeout','crash','error']) else 30000.0 for p in pairs] for side in ['baseline',variant]]
                ratio,lo,hi = paired_latency_ratio(*values)
                summary[field] = {'ratio':ratio,'ci95':[lo,hi], 'baseline_median':float(np.median(values[0])), 'candidate_median':float(np.median(values[1])),
                                  'status':'REGRESSED' if ratio>1.05 and lo>1 else 'improved' if ratio<.95 and hi<1 else 'same', 'pairs':len(pairs)}
            summary['failures'] = {side:{k:sum(bool(p['times'][side][k]) for p in pairs) for k in ['timeout','crash','error']} for side in ['baseline',variant]}
            result['metrics'][f'{name}.{variant}'] = summary
    result['load_end'] = list(os.getloadavg())
    write(dest,result)
    verify_receipt()


if __name__=='__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['accuracy','latency'])
    args = parser.parse_args()
    (accuracy if args.phase=='accuracy' else latency)()
