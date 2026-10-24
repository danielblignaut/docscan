#!/usr/bin/env python3
"""Check published denominators, receipts and frozen local round-two inputs."""
import json
from pathlib import Path
import run as base

HERE=Path(__file__).resolve().parent
EVIDENCE=HERE/'evidence'

def main():
    audit=json.loads((EVIDENCE/'audit.json').read_text())
    for name,digest in audit['artifacts'].items():assert base.sha(EVIDENCE/name)==digest
    for filename in ['id-round1.json','id-round2.json']:
        data=json.loads((EVIDENCE/filename).read_text())
        for c in data['candidates'].values():
            items=c['items'];s=c['summary']
            assert len(items)==len({i['id'] for i in items})==18
            assert s['passport_frames']==sum(i['positive'] for i in items)==12
            assert s['negative_frames']==sum(not i['positive'] for i in items)==6
            assert s['accepted_wrong']==sum(i['accepted_wrong'] for i in items)
            assert s['accepted_correct']==sum(i['accepted_correct'] for i in items)
            assert s['mrz_fields']==sum(len(i['fields']) for i in items)==120
            assert s['mrz_fields_correct']==sum(sum(i['fields'].values()) for i in items)
    for filename in ['barcode-round1.json','barcode-round2.json']:
        data=json.loads((EVIDENCE/filename).read_text())
        for ds,candidates in data['datasets'].items():
            frames,codes=(277,262) if ds=='barcode_public_dev' else (300,818)
            for c in candidates.values():
                assert len(c['items'])==len({i['id'] for i in c['items']})==frames
                prefix='barcode.'+ds+'.'
                assert c['metrics'][prefix+'recall']['n']==codes
                assert c['metrics'][prefix+'false_decode_frames']['n']==frames
                for m in c['metrics'].values():
                    if m['kind']=='rate':
                        assert m['n']==len(m['ids'])==len(m['ok'])
                        assert m['k']==m['ok'].count('1')
    for name,script,plan in [('id-round2','run_id_round2.py','candidates-id-round2.json'),('barcode-round2','run_barcode_round2.py','candidates-barcode-round2.json')]:
        frozen=json.loads((base.WORK/name/'frozen.json').read_text())
        assert frozen['runner_sha256']==base.sha(HERE/script)
        assert frozen.get('plan_sha256',frozen.get('config_sha256'))==base.sha(HERE/plan)
    frozen=json.loads((base.WORK/'barcode-round2/frozen.json').read_text())
    assert base.sha(base.WORK/'barcode-v2/barcode-results.json')==frozen['source_results_sha256']
    for iid,digest in frozen['prediction_sha256'].items():
        ds,index=iid.split(':')
        assert base.sha(base.WORK/'barcode-v2/private/barcode'/ds/(index+'.json'))==digest
    # The source snapshot is never rebuilt against shared working-tree edits.
    snapshot=json.loads((base.WORK/'snapshot.json').read_text())
    for relative,digest in snapshot['source'].items():assert base.sha(base.SOURCE/relative)==digest
    for name,digest in snapshot['models'].items():assert base.sha(base.WORK/'models'/name)==digest
    print('verified complete denominators, outcome totals, result receipts, both round-two freezes, all 577 cached predictions, source and models')

if __name__=='__main__':main()
