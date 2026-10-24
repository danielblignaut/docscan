#!/usr/bin/env python3
"""Measure fixed DEV field-text recovery; this is not a full-page CER scorer.

Truth includes only annotated values, omitting printed labels. A field is recovered
if its Unicode NFKC/casefold/whitespace-normalised value occurs at word boundaries
in the OCR output. Punctuation and diacritics remain significant. Unlabelled output
cannot be graded as hallucination. Frames are clustered by source layout; do not
claim independent-sample significance over repeated fields/camera frames.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import unicodedata

HERE=Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def normalise(text):
    return ' '.join(unicodedata.normalize('NFKC',text).casefold().split())

def recovered(truth,text):
    return re.search(r'(?<!\w)'+re.escape(normalise(truth))+r'(?!\w)',normalise(text)) is not None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path('/tmp/docscan-public-data/midv500'))
    parser.add_argument('--binary',required=True,type=Path)
    parser.add_argument('--engine-arg',action='append',default=[])
    parser.add_argument('--models',required=True,type=Path)
    parser.add_argument('--input',choices=['frame','rectified'],default='rectified')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--jobs',type=int,choices=[1,2],default=2)
    args=parser.parse_args()
    os.umask(0o077)
    manifest=HERE/'midv500-dev-v1.json'
    expected=json.loads(manifest.read_text())
    for item in expected['files']:
        file=args.data/item['path']
        if sha(file)!=item['sha256'] or file.stat().st_size!=item['size']:
            raise ValueError(f'changed pinned input: {item["path"]}')
    records=json.loads((args.data/'dev.json').read_text())
    if any(r['split']!='dev' for r in records):
        raise ValueError('only DEV permitted')
    def run(record):
        env={**os.environ,'RAYON_NUM_THREADS':'1','RTEN_NUM_THREADS':'1'}
        command=[str(args.binary.resolve()),*args.engine_arg,str(args.data/record[args.input])]
        started=time.monotonic()
        error=None
        try:
            result=subprocess.run(command,capture_output=True,text=True,env=env,timeout=180)
            if result.returncode:
                raise RuntimeError(result.stderr[-500:])
            output=json.loads(result.stdout.splitlines()[-1])
            error=output.get('error')
        except (subprocess.TimeoutExpired,RuntimeError,ValueError,IndexError) as exc:
            error=str(exc);output={}
        text=output.get('text','')
        if not text:
            text='\n'.join(line if isinstance(line,str) else line.get('text','') for line in output.get('lines',[]))
        fields=[{'id':record['id']+'/'+key,'ok':recovered(value['value'],text),'mrz':'<<' in value['value']}
                for key,value in record['fields'].items() if value['value'] and '*' not in value['value']]
        measured={'id':record['id'],'layout':record['layout'],'fields':fields,'ms':(time.monotonic()-started)*1000,
                  'error':error,'text':text,'output':output}
        print(record['id'],sum(f['ok'] for f in fields),'/',len(fields),flush=True)
        return measured
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        items=list(pool.map(run,records))
    fields=[f for item in items for f in item['fields']]
    mrz=[f for f in fields if f['mrz']]
    result={'schema':1,'scorer_sha256':sha(Path(__file__)),'manifest_sha256':sha(manifest),
            'binary':str(args.binary.resolve()),'binary_sha256':sha(args.binary),'input':args.input,'engine_args':args.engine_arg,
            'models':{p.name:sha(p) for p in sorted(args.models.iterdir()) if p.is_file() and p.suffix in ['.rten','.onnx']},
            'summary':{'frames':len(items),'fields':len(fields),'fields_recovered':sum(f['ok'] for f in fields),
                       'field_recovery':sum(f['ok'] for f in fields)/len(fields),'mrz_fields':len(mrz),
                       'mrz_fields_recovered':sum(f['ok'] for f in mrz),'errors':sum(bool(i['error']) for i in items)},
            'items':items}
    args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['summary'],indent=2))

if __name__=='__main__':main()
