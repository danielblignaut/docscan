#!/usr/bin/env python3
"""Paired DEV deltas from redacted evidence, never from source payloads."""
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent/'evidence'
def load(name):return json.loads((HERE/name).read_text())
def paired_rate(a,b):
    assert a['kind']==b['kind']=='rate'
    left=dict(zip(a['ids'],a['ok']));right=dict(zip(b['ids'],b['ok']))
    assert len(left)==a['n'] and set(left)==set(right)
    return {'n':a['n'],'reference_k':a['k'],'candidate_k':b['k'],
        'zero_to_one':[i for i in left if left[i]=='0' and right[i]=='1'],
        'one_to_zero':[i for i in left if left[i]=='1' and right[i]=='0']}

def main():
    b1=load('barcode-round1.json');b2=load('barcode-round2.json')
    report={'barcode':{},'id':{}}
    for ds,round1 in b1['datasets'].items():
        report['barcode'][ds]={}
        prefix='barcode.'+ds+'.';baseline=round1['native']['metrics']
        for name,c in {**round1,**b2['datasets'][ds]}.items():
            measures={key:paired_rate(baseline[prefix+key],c['metrics'][prefix+key]) for key in ['recall','all_codes','false_decode_frames','timeouts','crashes']}
            report['barcode'][ds][name]=measures
            print(ds,name,'recall',str(measures['recall']['candidate_k'])+'/'+str(measures['recall']['n']),
                'new_false_frames',len(measures['false_decode_frames']['zero_to_one']),
                'lost_codes',len(measures['recall']['one_to_zero']))
    first=load('id-round1.json')['candidates'];second=load('id-round2.json')['candidates']
    for name,c in {**first,**second}.items():
        ref='rectified_control' if name.startswith('rectified') else 'auto_quad' if name in second else 'raw'
        baseline={i['id']:i for i in first[ref]['items']}
        measures={'reference':ref,'summary':c['summary']}
        for metric in ['accepted_correct','accepted_wrong']:
            measures[metric]={'zero_to_one':[i['id'] for i in c['items'] if i[metric] and not baseline[i['id']][metric]],
                'one_to_zero':[i['id'] for i in c['items'] if baseline[i['id']][metric] and not i[metric]]}
        report['id'][name]=measures
        print('id',name,c['summary']['accepted_correct'],c['summary']['accepted_wrong'])
    (HERE/'paired-deltas.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
