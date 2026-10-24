#!/usr/bin/env python3
"""Frozen synthetic regression and non-text page probes for both native models."""
from collections import Counter
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from PIL import Image, ImageDraw
import numpy as np
from run import HERE,REPO,DATA,MODELS,module,score,artifact_state


def main():
    os.umask(0o077)
    protocol=json.loads((HERE/'negative-protocol.json').read_text())
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=HERE/'results/native-regression.json');args=parser.parse_args()
    target=args.output;target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():raise ValueError('Do not overwrite a completed probe')
    scorer=module('synthetic_scorer',REPO/'eval/text_eval.py')
    original=Path('/tmp/docscan-text-dev');baseline=json.loads((original/'results.json').read_text())
    pins={r['sample']:r['sha256'] for r in baseline['rows']}
    with tempfile.TemporaryDirectory() as temporary:
        samples=scorer.generate(Path(temporary))
        for name,image,truth in samples:
            if score.digest(image)!=pins[name] or score.digest(original/(name+'.png'))!=pins[name]:raise ValueError('Synthetic source changed')
    output=DATA/'regression';output.mkdir(exist_ok=True)
    negatives={};w,h=protocol['negative_size']
    rng=np.random.default_rng(protocol['negative_seed'])
    for name in protocol['negatives']:
        image=Image.new('RGB',(w,h),'white');draw=ImageDraw.Draw(image)
        if name in ['gray','black']:image=Image.new('RGB',(w,h),name)
        elif name=='table_lines':
            for y in range(40,h-40,60):draw.line((30,y,w-30,y),fill='black',width=2)
            for x in range(30,w,90):draw.line((x,40,x,h-60),fill='black',width=2)
        elif name=='checkerboard':
            for y in range(0,h,32):
                for x in range(0,w,32):
                    if (x//32+y//32)%2==0:draw.rectangle((x,y,x+31,y+31),fill='black')
        elif name=='speckles':
            array=np.full((h,w),255,dtype=np.uint8);array[rng.random((h,w))<.015]=0;image=Image.fromarray(array).convert('RGB')
        elif name=='rectangles':
            for i in range(8):draw.rectangle((40+i*8,50+i*95,400+i*20,100+i*95),fill=(i*25,80,130),outline='black')
        elif name=='gradient':
            array=np.tile(np.linspace(20,245,w,dtype=np.uint8),(h,1));image=Image.fromarray(array).convert('RGB')
        path=output/(name+'.png');image.save(path);negatives[name]=path
    report={'protocol':protocol,'runner_sha256':score.digest(__file__),'results':{},'negative_hashes':{n:score.digest(p) for n,p in negatives.items()},'limits':'Generated regressions only; positive corpus is unchanged and negatives are not real acquired blank documents.'}
    for mode in protocol['modes']:
        tier,profile=mode.split('-');folder=DATA/'native'/tier;binary=folder/'reader'
        build=json.loads((folder/'build.json').read_text());det=MODELS/'tiny_det/inference.onnx';rec=MODELS/f'{tier}_rec/inference.onnx'
        if score.digest(binary)!=build['binary_sha256']:raise ValueError('Probe changed')
        artifacts=[binary,det,rec];before=artifact_state(artifacts)
        def read(path):
            cmd=[str(binary),str(det),str(rec),str(path)]+(['detail'] if profile=='detail' else [])
            result=subprocess.run(cmd,text=True,capture_output=True,check=True,timeout=protocol['timeout_seconds'],env={**os.environ,'RTEN_NUM_THREADS':'1','RAYON_NUM_THREADS':'1'})
            result=json.loads(result.stdout)
            if 'error' in result:raise ValueError(result['error'])
            return result
        rows=[]
        for name,_,truth in samples:
            result=read(original/(name+'.png'));expected,actual=scorer.normalized(truth),scorer.normalized(result['text'])
            a,b=Counter(expected.split()),Counter(actual.split())
            (output/(mode+'-'+name+'.json')).write_text(json.dumps(result)+'\n')
            rows.append({'id':name,'characters':len(expected),'edits':scorer.distance(expected,actual),'words':sum(a.values()),'correct_words':sum((a&b).values()),'extra_words':sum((b-a).values())})
        negative=[]
        for name,path in negatives.items():
            result=read(path);(output/(mode+'-'+name+'.json')).write_text(json.dumps(result)+'\n')
            negative.append({'id':name,'nonempty':bool(result['text'].strip()),'characters':len(result['text'].strip())})
        if artifact_state(artifacts)!=before:raise ValueError('Artifacts changed')
        report['results'][mode]={'build':build,'positive_rows':rows,'negative_rows':negative,'cer':sum(r['edits'] for r in rows)/sum(r['characters'] for r in rows),'word_recall':sum(r['correct_words'] for r in rows)/sum(r['words'] for r in rows),'extra_words':sum(r['extra_words'] for r in rows),'false_text_pages':sum(r['nonempty'] for r in negative)}
        print(mode,{k:report['results'][mode][k] for k in ['cer','word_recall','extra_words','false_text_pages']},flush=True)
    target.write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
