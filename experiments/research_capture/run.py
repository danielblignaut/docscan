#!/usr/bin/env python3
"""Frozen DEV-only capture experiments; source text/media stays in private /tmp.

Use the bench venv. prepare.py must have snapshotted dd96ed0 and the native
scan example must have been built in WORK/target. Results are not main-harness
full-suite or latency verdicts. No training and no acceptance-policy changes.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
WORK = Path('/tmp/docscan-research-capture')
SOURCE = WORK/'source'
DATA = Path('/tmp/docscan-public-data/midv500')
BENCH_DATA = Path('/tmp/docscan-bench')
os.environ['RAYON_NUM_THREADS'] = '1'
os.environ['RTEN_NUM_THREADS'] = '1'
cv2.setNumThreads(1)
sys.path.insert(0,str(SOURCE/'bench'))
from lib.common import safe_digest
from suites.barcode import score as score_barcodes

spec = importlib.util.spec_from_file_location('frozen_score_id',SOURCE/'experiments/public_id/score_id.py')
id_scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(id_scorer)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')

def verify(root, manifest, encoded=False):
    if manifest.get('split','dev')!='dev':
        raise ValueError('DEV only')
    for entry in manifest['files']:
        path = root/entry['path']
        digest = sha(path)
        if (safe_digest(digest) if encoded else digest)!=entry['sha256'] or path.stat().st_size!=entry['bytes' if encoded else 'size']:
            raise ValueError('Pinned input changed: '+entry['path'])

def padded(img, fraction):
    border = max(1,round(min(img.shape[:2])*fraction))
    return cv2.copyMakeBorder(img,border,border,border,border,cv2.BORDER_CONSTANT,value=(255,255,255))

def quad_transform(img, config):
    """Image-only classical quadrilateral proposal; no annotation access."""
    h,w = img.shape[:2]
    scale = min(1.0,config['detection_long_side']/max(h,w))
    small = cv2.resize(img,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
    kernel = config['gaussian_kernel']
    gray = cv2.GaussianBlur(gray,(kernel,kernel),0)
    edges = cv2.Canny(gray,*config['canny'])
    edges = cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((config['close_kernel'],)*2,np.uint8))
    contours,_ = cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    options = []
    for contour in contours:
        poly = cv2.approxPolyDP(contour,config['approx_perimeter_fraction']*cv2.arcLength(contour,True),True)
        if len(poly)!=4 or not cv2.isContourConvex(poly):
            continue
        area = abs(cv2.contourArea(poly))/(small.shape[0]*small.shape[1])
        if not config['area_fraction'][0]<=area<=config['area_fraction'][1]:
            continue
        points = poly[:,0,:].astype(np.float32)/scale
        # Angular ordering avoids duplicated corners from sum/difference extrema.
        centre = points.mean(axis=0)
        points = points[np.argsort(np.arctan2(points[:,1]-centre[1],points[:,0]-centre[0]))]
        points = np.roll(points,-int(np.argmin(points.sum(axis=1))),axis=0)
        sides = np.linalg.norm(np.roll(points,-1,axis=0)-points,axis=1)
        if min(sides)<config['minimum_edge']:
            continue
        ow,oh = (sides[0]+sides[2])/2,(sides[1]+sides[3])/2
        ratio = max(ow,oh)/min(ow,oh)
        if not config['aspect_ratio'][0]<=ratio<=config['aspect_ratio'][1]:
            continue
        options.append((area,points,ow,oh))
    if not options:
        return img,{'found':False}
    area,points,ow,oh = max(options,key=lambda x:x[0])
    factor = min(1,config['warp_long_side_cap']/max(ow,oh))
    ow,oh = max(1,round(ow*factor)),max(1,round(oh*factor))
    target = np.array([[0,0],[ow-1,0],[ow-1,oh-1],[0,oh-1]],np.float32)
    warp = cv2.warpPerspective(img,cv2.getPerspectiveTransform(points,target),(ow,oh),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    if oh>ow:
        warp = cv2.rotate(warp,cv2.ROTATE_90_CLOCKWISE)
    return padded(warp,config['padding_fraction']),{'found':True,'area_fraction':area,'corners':points.tolist()}

def native(path, config, barcode=False):
    command = [str(WORK/'bin/scan'),'--models='+str(WORK/'models')]
    if barcode:
        command.append('--barcodes')
    command.append(str(path))
    start = time.monotonic()
    status = {'timeout':False,'crash':False,'error':False}
    try:
        result = subprocess.run(command,capture_output=True,text=True,env={**os.environ,'SCAN_MAX_WIDTH':str(config['barcode_max_width'] if barcode else config['id_max_width'])},timeout=config['barcode_timeout_seconds'] if barcode else config['id_timeout_seconds'])
        if result.returncode:
            status['crash'] = True
            output = {}
        else:
            output = json.loads(result.stdout.splitlines()[-1])
            if not barcode and output.get('model_directory')!=str(WORK/'models'):
                raise ValueError('Model directory was not confirmed')
    except subprocess.TimeoutExpired:
        status['timeout'] = True
        output = {}
    except (ValueError,IndexError):
        status['error'] = True
        output = {}
    output.update(status)
    return output,round((time.monotonic()-start)*1000,3)

def frozen_provenance(config, suite):
    frozen = WORK/('frozen-'+suite+'.json')
    if frozen.exists():
        raise FileExistsError('A trial already exists; retain it and create a new declared round')
    if not (WORK/'bin/scan').exists():
        shutil.copy2(WORK/'target/release/examples/scan',WORK/'bin/scan')
    snap = json.loads((WORK/'snapshot.json').read_text())
    for relative,digest in snap['source'].items():
        if sha(SOURCE/relative)!=digest:
            raise ValueError('Source snapshot changed')
    for name,digest in snap['models'].items():
        if sha(WORK/'models'/name)!=digest:
            raise ValueError('Model snapshot changed')
    provenance = {'frozen_utc':datetime.now(timezone.utc).isoformat(),'suite':suite,'config':config,
        'config_sha256':sha(HERE/'candidates.json'),'runner_sha256':sha(Path(__file__)),
        'zxing_worker_sha256':sha(HERE/'zxing_worker.py'),
        'manifests':{name:sha(SOURCE/name) for name in ['bench/manifests/barcode_public_dev.json','bench/manifests/barcode_synth_dev.json','experiments/public_id/midv500-dev-v1.json']},
        'binary_sha256':sha(WORK/'bin/scan'),'snapshot_sha256':sha(WORK/'snapshot.json'),
        'models':snap['models'],'packages':{name:importlib.metadata.version(name) for name in ['numpy','opencv-python-headless','pillow','zxing-cpp']},
        'scorers':{name:sha(SOURCE/name) for name in ['bench/suites/barcode.py','bench/lib/common.py','bench/lib/stats.py','experiments/public_id/score_id.py']},
        'thread_environment':{'RAYON_NUM_THREADS':'1','RTEN_NUM_THREADS':'1','opencv_threads':1},
        'native_flags':{'id':['--models='+str(WORK/'models')],'barcode':['--models='+str(WORK/'models'),'--barcodes']}}
    write(frozen,provenance)
    return provenance

def run_id(config):
    pin = SOURCE/'experiments/public_id/midv500-dev-v1.json'
    verify(DATA,json.loads(pin.read_text()))
    records = json.loads((DATA/'dev.json').read_text())
    assert len(records)==18 and all(r['split']=='dev' for r in records)
    provenance = frozen_provenance(config,'id')
    provenance['manifest_sha256'] = sha(pin)
    result = {'provenance':provenance,'candidates':{}}
    for candidate in config['id_candidates']:
        def trial(pair):
            i,record = pair
            input_kind = 'rectified' if candidate.startswith('rectified') else 'frame'
            path = DATA/record[input_kind]
            detail = {}
            if candidate not in ['raw','rectified_control']:
                image = cv2.imread(str(path))
                if candidate=='raw_cw90': image = cv2.rotate(image,cv2.ROTATE_90_CLOCKWISE)
                elif candidate=='auto_quad': image,detail = quad_transform(image,config['auto_quad'])
                elif candidate=='rectified_pad': image = padded(image,config['rectified_pad_fraction'])
                else: raise ValueError(candidate)
                path = WORK/'derived'/candidate/(str(i)+'.png')
                path.parent.mkdir(parents=True,exist_ok=True)
                assert cv2.imwrite(str(path),image)
            output,ms = native(path,config)
            measured = {'id':record['id'],'output':output,'input_sha256':sha(path),'wall_ms':ms,'geometry':detail}
            write(WORK/'private/id'/candidate/(str(i)+'.json'),measured)
            print('id',candidate,i,'complete',flush=True)
            return measured
        with ThreadPoolExecutor(config['workers']) as pool:
            measured = list(pool.map(trial,enumerate(records)))
        scored = id_scorer.score({'items':measured,'input':candidate,'binary_sha256':provenance['binary_sha256']},records)
        for item,trial_result in zip(scored['items'],measured):
            item.update({key:trial_result[key] for key in ['input_sha256','wall_ms','geometry']})
            item['status'] = {key:trial_result['output'][key] for key in ['timeout','crash','error']}
        result['candidates'][candidate] = scored
        write(WORK/'id-results.json',result)
        print(candidate,scored['summary'],flush=True)
    return result

def zxing(path, config):
    # Isolate optional decoder too: it receives exactly one fixed DEV image.
    command = [sys.executable,str(HERE/'zxing_worker.py'),str(path)]
    start = time.monotonic()
    try:
        completed = subprocess.run(command,capture_output=True,text=True,timeout=config['barcode_timeout_seconds'])
        result = json.loads(completed.stdout) if completed.returncode==0 else {'barcodes':[],'crash':True}
    except subprocess.TimeoutExpired:
        result = {'barcodes':[],'timeout':True}
    return result,round((time.monotonic()-start)*1000,3)

def run_barcode(config):
    loaded = {}
    for dataset in ['barcode_public_dev','barcode_synth_dev']:
        pin = SOURCE/'bench/manifests'/(dataset+'.json')
        manifest = json.loads(pin.read_text())
        root = BENCH_DATA/manifest['root']
        verify(root,manifest,encoded=True)
        rows = [json.loads(line) for line in (root/'truth.jsonl').read_text().splitlines() if line.strip()]
        for index,row in enumerate(rows):
            row['id'] = dataset+':'+str(index)
            row['path'] = str(root/row['image'])
        loaded[dataset] = (rows,sha(pin))
    provenance = frozen_provenance(config,'barcode')
    provenance['zxing_worker_sha256'] = sha(HERE/'zxing_worker.py')
    provenance['manifests'] = {name:value[1] for name,value in loaded.items()}
    result = {'provenance':provenance,'datasets':{}}
    for dataset,(rows,_) in loaded.items():
        def trial(pair):
            i,row = pair
            original = Path(row['path'])
            baseline,ms = native(original,config,barcode=True)
            variants = {'native':(baseline,ms)}
            img = cv2.imread(str(original))
            for name,transformed in [('native_plus_cw90',cv2.rotate(img,cv2.ROTATE_90_CLOCKWISE)),('native_plus_half',cv2.resize(img,(max(1,img.shape[1]//2),max(1,img.shape[0]//2)),interpolation=cv2.INTER_AREA))]:
                path = WORK/'derived'/dataset/name/(str(i)+'.png')
                path.parent.mkdir(parents=True,exist_ok=True)
                assert cv2.imwrite(str(path),transformed)
                extra,extra_ms = native(path,config,barcode=True)
                found = {(b['format'],b['text']):b for out in [baseline,extra] for b in out.get('barcodes',[])}
                variants[name] = ({'barcodes':list(found.values()),**{key:bool(baseline.get(key) or extra.get(key)) for key in ['timeout','crash','error']}},ms+extra_ms)
            variants['zxingcpp'] = zxing(original,config)
            write(WORK/'private/barcode'/dataset/(str(i)+'.json'),{'input_sha256':sha(original),'variants':variants})
            if i%25==0: print(dataset,i,'complete',flush=True)
            return variants
        with ThreadPoolExecutor(config['workers']) as pool:
            trials = list(pool.map(trial,enumerate(rows)))
        result['datasets'][dataset] = {}
        for candidate in config['barcode_candidates']:
            outputs = {r['path']:t[candidate][0] for r,t in zip(rows,trials)}
            metrics = score_barcodes(dataset,rows,outputs)
            # Precision's original scorer IDs contain payloads; retain only opaque hashes.
            for metric in metrics.values():
                if 'ids' in metric:
                    metric['ids'] = [hashlib.sha256(i.encode()).hexdigest() for i in metric['ids']]
            items = [{'id':r['id'],'input_sha256':sha(r['path']),'wall_ms':t[candidate][1],
                      'timeout':bool(t[candidate][0].get('timeout')),'crash':bool(t[candidate][0].get('crash')),
                      'error':bool(t[candidate][0].get('error'))} for r,t in zip(rows,trials)]
            result['datasets'][dataset][candidate] = {'metrics':metrics,'items':items}
            prefix = 'barcode.'+dataset+'.'
            print(dataset,candidate,{key:metrics[prefix+key]['k'] for key in ['recall','false_decode_frames','timeouts','crashes']},flush=True)
        write(WORK/'barcode-results.json',result)
    return result

if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite',choices=['id','barcode'])
    args = parser.parse_args()
    os.umask(0o077)
    config = json.loads((HERE/'candidates.json').read_text())
    assert config['split']=='dev' and config['workers']==2
    (run_id if args.suite=='id' else run_barcode)(config)
    for name,digest in json.loads((WORK/'snapshot.json').read_text())['models'].items():
        assert sha(WORK/'models'/name)==digest
    print('completed',args.suite,flush=True)
