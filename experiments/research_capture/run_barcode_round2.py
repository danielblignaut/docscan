#!/usr/bin/env python3
"""Predeclared format-scoped retries from frozen predictions, unchanged scorer."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import run as base
from suites.barcode import score

HERE=Path(__file__).resolve().parent
WORK=base.WORK/'barcode-round2'
CACHE=base.WORK/'barcode-v2'

def main():
    os.umask(0o077)
    WORK.mkdir(exist_ok=False)
    config=json.loads((HERE/'candidates-barcode-round2.json').read_text())
    assert config['split']=='dev'
    # Import only the canonical conversion helper. Never call entries/fetch/main.
    source=subprocess.check_output(['git','show','dd96ed0d193cbc5e2a316bd9234524a08a44dbfc:bench/data/import_barcodes_public.py'],cwd=HERE.parents[1])
    helper=WORK/'pinned_importer.py';helper.write_bytes(source)
    spec=importlib.util.spec_from_file_location('pinned_importer',helper)
    importer=importlib.util.module_from_spec(spec);spec.loader.exec_module(importer)
    original=json.loads((CACHE/'barcode-results.json').read_text())
    datasets={}
    prediction_hashes={}
    for dataset in ['barcode_public_dev','barcode_synth_dev']:
        pin=base.SOURCE/'bench/manifests'/(dataset+'.json');manifest=json.loads(pin.read_text())
        root=base.BENCH_DATA/manifest['root'];base.verify(root,manifest,True)
        rows=[json.loads(s) for s in (root/'truth.jsonl').read_text().splitlines() if s.strip()]
        predictions=[]
        for i,row in enumerate(rows):
            row['id']=dataset+':'+str(i);row['path']=str(root/row['image'])
            p=CACHE/'private/barcode'/dataset/(str(i)+'.json')
            prediction_hashes[dataset+':'+str(i)]=base.sha(p)
            predictions.append(json.loads(p.read_text()))
            assert predictions[-1]['input_sha256']==base.sha(row['path'])
        datasets[dataset]=(rows,predictions)
    provenance={'frozen_utc':datetime.now(timezone.utc).isoformat(),'config':config,
        'config_sha256':base.sha(HERE/'candidates-barcode-round2.json'),'runner_sha256':base.sha(Path(__file__)),
        'source_results_sha256':base.sha(CACHE/'barcode-results.json'),
        'base_provenance':original['provenance'],'prediction_sha256':prediction_hashes,'importer_sha256':base.sha(helper)}
    base.write(WORK/'frozen.json',provenance)
    results={'provenance':provenance,'datasets':{}}
    for dataset,(rows,predictions) in datasets.items():
        results['datasets'][dataset]={}
        for candidate in config['candidates']:
            outputs={}
            for row,prediction in zip(rows,predictions):
                variants=prediction['variants'];native=variants['native'][0]
                if candidate=='zxingcpp_equivalent_formats':
                    raw=variants['zxingcpp'][0]
                    codes=[]
                    for b in raw.get('barcodes',[]):
                        fmt,text=b['format'],b['text']
                        if fmt=='code39extended':fmt='code39'
                        if fmt in ['upca','upce'] and len(text)==13 and text.isdigit() and text.startswith('0'):
                            if fmt=='upca':text=text[1:]
                            else:text=importer.upca_to_upce(text[1:]) or text
                        codes.append({'format':fmt,'text':text})
                    outputs[row['path']]={**raw,'barcodes':codes}
                else:
                    found={(b['format'],b['text']):b for b in native.get('barcodes',[])}
                    used=[native]
                    passes=['native_plus_cw90'] if candidate.endswith('cw90') else ['native_plus_half'] if candidate.endswith('half') else ['native_plus_cw90','native_plus_half']
                    for name in passes:
                        extra=variants[name][0];used.append(extra)
                        for b in extra.get('barcodes',[]):
                            if b['format'] in config['matrix_formats']:found[(b['format'],b['text'])]=b
                    outputs[row['path']]={'barcodes':list(found.values()),**{k:any(v.get(k,False) for v in used) for k in ['timeout','crash','error']}}
            metrics=score(dataset,rows,outputs)
            for metric in metrics.values():
                if 'ids' in metric:metric['ids']=[base.hashlib.sha256(i.encode()).hexdigest() for i in metric['ids']]
            items=[{'id':r['id'],'input_sha256':p['input_sha256']} for r,p in zip(rows,predictions)]
            results['datasets'][dataset][candidate]={'metrics':metrics,'items':items,'inference':'cached complete DEV predictions; no timing estimate'}
            prefix='barcode.'+dataset+'.'
            print(dataset,candidate,{key:(metrics[prefix+key]['k'],metrics[prefix+key]['n']) for key in ['recall','false_decode_frames','timeouts','crashes']},flush=True)
        base.write(WORK/'results.json',results)
    print('completed barcode round2',flush=True)

if __name__=='__main__':main()
