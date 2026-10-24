#!/usr/bin/env python3
"""Score the structured ID output stored by evaluate.py, separately from text OCR.

This scorer never uses its input's field-recovery summary: scan emits its MRZ
separately from ordinary text. Expected values come directly from publisher MRZ
truth, never from the scanner under evaluation. Only TD3 passports are positives;
unsupported Estonian card fronts are negatives for automatic acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path

FIELDS=('document_code','issuing_state','surname','given_names','document_number',
        'nationality','date_of_birth','sex','date_of_expiry','optional_data')

def expected(record):
    lines=[v['value'] for v in record['fields'].values() if '<' in v['value']]
    if len(lines)!=2 or any(len(s)!=44 for s in lines) or not lines[0].startswith('P'):
        return None
    a,b=lines
    name=a[5:].split('<<',1)
    filler=lambda s:' '.join(s.replace('<',' ').split())
    return dict(zip(FIELDS,[filler(a[:2]),a[2:5],filler(name[0]),filler(name[1]),
        filler(b[:9]),b[10:13],b[13:19],b[20],b[21:27],filler(b[28:42])]))

def score(results,truth):
    byid={r['id']:r for r in truth}
    if len(byid)!=len(truth) or len(results['items'])!=len(truth) or set(byid)!={i['id'] for i in results['items']}:
        raise ValueError('input must contain exactly the fixed DEV items')
    outcomes=[]
    for item in results['items']:
        wanted=expected(byid[item['id']]); output=item['output']; accepted=output.get('accepted',False)
        actual=output.get('mrz') or {}
        fields={key:actual.get(key)==value for key,value in wanted.items()} if wanted else {}
        correct=bool(wanted) and all(fields.values()) and output.get('kind')=='other_passport'
        outcomes.append({'id':item['id'],'positive':wanted is not None,'accepted':accepted,
                         'accepted_correct':accepted and correct,'accepted_wrong':accepted and not correct,'fields':fields})
    positives=[i for i in outcomes if i['positive']]
    negatives=[i for i in outcomes if not i['positive']]
    return {'input_sha256':results.get('binary_sha256'),'input_kind':results['input'],
            'summary':{'passport_frames':len(positives),'negative_frames':len(negatives),
                       'accepted_correct':sum(i['accepted_correct'] for i in positives),
                       'accepted_wrong':sum(i['accepted_wrong'] for i in outcomes),
                       'negative_false_accepts':sum(i['accepted'] for i in negatives),
                       'mrz_fields_correct':sum(sum(i['fields'].values()) for i in positives),
                       'mrz_fields':len(positives)*len(FIELDS)},'items':outcomes}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('results',type=Path)
    p.add_argument('--data',type=Path,default=Path('/tmp/docscan-public-data/midv500'))
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    pinned=json.loads((Path(__file__).parent/'midv500-dev-v1.json').read_text())
    entry=next(i for i in pinned['files'] if i['path']=='dev.json')
    raw=(a.data/'dev.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('truth differs from pin')
    result=score(json.loads(a.results.read_text()),json.loads(raw))
    result['scorer_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['results_sha256']=hashlib.sha256(a.results.read_bytes()).hexdigest()
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['summary'],indent=2))
