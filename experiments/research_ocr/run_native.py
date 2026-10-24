#!/usr/bin/env python3
"""Fixed-input native feasibility of tiny detection plus small recognition."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import time
from run import HERE, REPO, DATA, MODELS, score


def main():
    os.umask(0o077)
    protocol=json.loads((HERE/'native-protocol.json').read_text())
    samples,frozen=score.materialize()
    if frozen!=json.loads((score.HERE/'ocr-dev-v1.json').read_text()):raise ValueError('Inputs changed')
    for tier in protocol['recognizers']:
        folder=DATA/'native'/tier; binary=folder/'reader'
        build=json.loads((folder/'build.json').read_text())
        if score.digest(binary)!=build['binary_sha256']:raise ValueError('Executable changed')
        detector=MODELS/'tiny_det/inference.onnx';recognizer=MODELS/f'{tier}_rec/inference.onnx'
        if {'detector':score.digest(detector),'recognizer':score.digest(recognizer)}!=build['model_hashes']:raise ValueError('Models changed')
        artifacts=[binary,detector,recognizer];before=score.model_state(artifacts)
        for profile in protocol['profiles']:
            mode=f'native-tiny-{tier}-{profile}'
            target=HERE/'results'/(mode+'.json')
            if target.exists():raise ValueError('Refusing to overwrite results')
            raw=DATA/mode;raw.mkdir(exist_ok=True)
            def infer(sample):
                cmd=[str(binary),str(detector),str(recognizer),sample['path']]
                if profile=='detail':cmd.append('detail')
                try:
                    process=subprocess.run(cmd,text=True,capture_output=True,timeout=protocol['timeout_seconds_per_page'],
                            env={**os.environ,'RTEN_NUM_THREADS':'1','RAYON_NUM_THREADS':'1'})
                    if process.returncode:raise RuntimeError('Native process failed')
                    output=json.loads(process.stdout)
                    if 'error' in output:raise ValueError(output['error'])
                except (RuntimeError,ValueError,subprocess.TimeoutExpired) as error:
                    output={'text':'','lines':[],'error':type(error).__name__}
                (raw/(sample['id']+'.json')).write_text(json.dumps(output,ensure_ascii=False)+'\n')
                return sample,output
            rows=[];groups=defaultdict(list);start=time.monotonic()
            with ThreadPoolExecutor(max_workers=2) as pool:
                for sample,output in pool.map(infer,samples):
                    fields=[]
                    if sample['source']=='bankstatemently':fields.append({'label':'full_page',**score.token_score(sample['text'],output['text'])})
                    else:
                        for f in sample['fields']:
                            fields.append({'label':f['label'],**score.token_score(f['text'],score.region_text(output['lines'],f['bbox']))})
                    for f in fields:
                        groups[sample['source']].append(f);groups[sample['source']+'.'+f['label']].append(f)
                    rows.append({'id':sample['id'],'source':sample['source'],'failed':'error' in output,'scores':fields})
                    print(mode,sample['id'],flush=True)
            if score.model_state(artifacts)!=before:raise ValueError('Artifacts changed during run')
            report={'mode':mode,'protocol':protocol,'build':build,'scorer_sha256':score.digest(score.__file__),
                    'runner_sha256':score.digest(__file__),'dataset_sha256':score.digest(score.HERE/'ocr-dev-v1.json'),
                    'summary':{k:score.summary(v) for k,v in sorted(groups.items())},'rows':rows,
                    'failed_pages':sum(r['failed'] for r in rows),'wall_seconds_descriptive':time.monotonic()-start,
                    'limits':'Native isolated probe only; no production/default or browser change; fixed DEV with correlated layouts.'}
            target.write_text(json.dumps(report,indent=2)+'\n')
            print(mode,{k:v for k,v in report['summary'].items() if '.' not in k},flush=True)

if __name__=='__main__':main()
