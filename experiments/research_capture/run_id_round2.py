#!/usr/bin/env python3
"""Predeclared automatic-crop margin ablation on all 18 pinned DEV frames."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import cv2
import run as base

HERE=Path(__file__).resolve().parent
OUT=base.WORK/'id-round2'

def main():
    os.umask(0o077)
    OUT.mkdir(exist_ok=False)
    config=json.loads((HERE/'candidates.json').read_text())
    plan=json.loads((HERE/'candidates-id-round2.json').read_text())
    assert plan['split']=='dev'
    pin=base.SOURCE/'experiments/public_id/midv500-dev-v1.json'
    base.verify(base.DATA,json.loads(pin.read_text()))
    records=json.loads((base.DATA/'dev.json').read_text())
    assert len(records)==18 and all(r['split']=='dev' for r in records)
    snapshot=json.loads((base.WORK/'snapshot.json').read_text())
    for name,digest in snapshot['models'].items():assert base.sha(base.WORK/'models'/name)==digest
    first=json.loads((base.WORK/'id-results.json').read_text())
    assert base.sha(base.WORK/'bin/scan')==first['provenance']['binary_sha256']
    provenance={'frozen_utc':datetime.now(timezone.utc).isoformat(),'plan':plan,
        'plan_sha256':base.sha(HERE/'candidates-id-round2.json'),'runner_sha256':base.sha(Path(__file__)),
        'base_runner_sha256':base.sha(HERE/'run.py'),'base_config_sha256':base.sha(HERE/'candidates.json'),
        'source_round_sha256':base.sha(base.WORK/'id-results.json'),'base_provenance':first['provenance']}
    assert provenance['base_runner_sha256']==first['provenance']['runner_sha256']
    base.write(OUT/'frozen.json',provenance)
    results={'provenance':provenance,'candidates':{}}
    original_pad=base.padded
    # Match v1 for nonzero margins; zero is an explicit no-op in this ablation.
    base.padded=lambda image,fraction: image if fraction==0 else original_pad(image,fraction)
    for candidate in plan['candidates']:
        name=candidate['name']
        geometry={**config['auto_quad'],'padding_fraction':candidate['padding_fraction']}
        def trial(pair):
            i,record=pair
            img=cv2.imread(str(base.DATA/record['frame']))
            transformed,detail=base.quad_transform(img,geometry)
            path=OUT/'derived'/name/(str(i)+'.png')
            path.parent.mkdir(parents=True,exist_ok=True)
            assert cv2.imwrite(str(path),transformed)
            output,ms=base.native(path,config)
            measured={'id':record['id'],'output':output,'input_sha256':base.sha(path),'geometry':detail,'wall_ms':ms}
            base.write(OUT/'private'/name/(str(i)+'.json'),measured)
            print(name,i,'complete',flush=True)
            return measured
        with ThreadPoolExecutor(2) as pool:measured=list(pool.map(trial,enumerate(records)))
        scored=base.id_scorer.score({'items':measured,'input':name,'binary_sha256':first['provenance']['binary_sha256']},records)
        for item,m in zip(scored['items'],measured):
            item.update({key:m[key] for key in ['input_sha256','geometry','wall_ms']})
            item['status']={key:m['output'][key] for key in ['timeout','crash','error']}
        results['candidates'][name]=scored
        base.write(OUT/'results.json',results)
        print(name,scored['summary'],flush=True)
    for name,digest in snapshot['models'].items():assert base.sha(base.WORK/'models'/name)==digest
    print('completed id round2',flush=True)

if __name__=='__main__':main()
