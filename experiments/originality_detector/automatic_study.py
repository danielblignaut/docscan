#!/usr/bin/env python3
"""Freeze/train/export/evaluate automatic grid arms on unchanged source-TRAIN cohort."""
from __future__ import annotations
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
import argparse
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image
from automatic import GRID,features
from detector import score,decide
from study import HERE,private_dir,digest,write,source_hashes,train,evaluate,cohort_counts
from receipts import verify,within,verify_notice_registry
from real_study import verify_partition


def sources():
    return source_hashes() | {n:digest(HERE/n) for n in ('automatic.py','automatic_study.py')}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();os.umask(0o077);root=private_dir(a.output)
    manifest=verify(a.data);verify_notice_registry(a.data);records=manifest['records'];verify_partition(records)
    config=json.loads((HERE/'protocol.json').read_text())
    config['candidates']=['constant_unknown','automatic_strict','automatic_calibration_only']
    hashes=sources()
    freeze=dict(cohort=cohort_counts(records),timestamp=datetime.now(timezone.utc).isoformat(),grid=GRID,config=config,sources=hashes,
                sealed_manifest_sha256=digest(a.data/'sealed-manifest.json'),
                counts={s:sum(r['split']==s for r in records) for s in ('train','calibration','dev')},
                thresholds={'strict':'max(log(9), max calibration-negative logit)',
                            'calibration_only':'max calibration-negative logit; strict > comparison'},
                note='Two operating points fixed before automatic inference; no annotation/label-guided patch selection')
    write(root/'freeze.json',freeze);print('FROZEN automatic',freeze['counts'],flush=True)
    rows=[]
    for i,r in enumerate(records):
        start=time.monotonic()
        row=dict(id=r['id'],global_features=None,context_features=None,error=None)
        try:
            if r['acquisition_error']:raise ValueError('acquisition failure')
            path=within(a.data,r['path'])
            if digest(path)!=r['sha256']:raise ValueError('image changed')
            with Image.open(path) as im:rgb=np.asarray(im.convert('RGB'))
            values=features(rgb).tolist()
            row.update(global_features=values,context_features=values)
        except Exception as exc:row['error']=type(exc).__name__+': '+str(exc)
        row['seconds']=time.monotonic()-start;rows.append(row)
        if (i+1)%20==0:print('automatic features',i+1,'/',len(records),flush=True)
    write(root/'features.json',rows)
    models={'constant_unknown':None};failures={}
    for name in config['candidates'][1:]:
        cfg=copy.deepcopy(config)
        if name=='automatic_calibration_only':cfg['decision']['minimum_logit']=-1e12
        try:
            model=train(cfg,records,rows,'native_patch_texture')
            model.update(input_protocol='rgb_grid_3x3_native224_q75',grid=GRID,operating_point=name,
                scope='DLC_source_TRAIN_automatic_screen_recapture_pilot',supported_copy_kinds=['screen'],
                training_data_license=manifest['license'],weights_license='Private research artifact; redistribution rights not inferred',
                provenance=dict(sources=hashes,freeze_sha256=digest(root/'freeze.json')))
            write(root/(name+'.model.json'),model);models[name]=model
        except ValueError as exc:models[name]=None;failures[name]=str(exc)
    write(root/'models-frozen.json',dict(models={n:digest(root/(n+'.model.json')) for n,m in models.items() if m},failures=failures))
    summary=dict(cohort=cohort_counts(records),kind='automatic_3x3_grid_real_pilot',source_train_only=True,grid=GRID,sources=hashes,
        freeze_sha256=digest(root/'freeze.json'),sealed_manifest_sha256=freeze['sealed_manifest_sha256'],
        candidates={},training_failures=failures,production_promotion=False,test_access=False,
        note='Each arm runs on same 72 DEV frames; no issuer-originality claims or posterior confidence')
    for name,model in models.items():
        metrics={}
        for split in ('calibration','dev'):
            agg,preds=evaluate(model,records,rows,split)
            if name in failures:
                agg['model_training_failure']=failures[name];agg['failures']=agg['items']
                for row in preds:row.update(failure=True,reason='model_training_failure')
            subset=[r for r in records if r['split']==split]
            agg['attack_specimens']=len({r['specimen'] for r in subset if r['label']=='screen_recapture'})
            agg['detected_attack_specimens']=len({r['specimen'] for r,v in zip(subset,preds) if r['label']=='screen_recapture' and v['status']=='copy_indicated'})
            agg['by_document_type']={t:dict(attack_items=sum(r['type']==t and r['label']=='screen_recapture' for r in subset),
                detected_attacks=sum(r['type']==t and r['label']=='screen_recapture' and v['status']=='copy_indicated' for r,v in zip(subset,preds)),
                negative_items=sum(r['type']==t and r['label']=='bona_fide_capture' for r in subset),
                false_positives=sum(r['type']==t and r['label']=='bona_fide_capture' and v['status']=='copy_indicated' for r,v in zip(subset,preds))) for t in sorted({r['type'] for r in subset})}
            metrics[split]=agg;write(root/(name+'.'+split+'.predictions.json'),preds)
        summary['candidates'][name]=dict(metrics=metrics,thresholds=model['thresholds'] if model else None,
                                       model_sha256=digest(root/(name+'.model.json')) if model else None)
    if sources()!=hashes:raise ValueError('source changed')
    verify(a.data);verify_notice_registry(a.data)
    if digest(a.data/'sealed-manifest.json')!=freeze['sealed_manifest_sha256']:raise ValueError('sealed manifest changed')
    for r in records:
        if not r['acquisition_error'] and digest(within(a.data,r['path']))!=r['sha256']:raise ValueError('input changed')
    write(root/'summary.json',summary)
    print(json.dumps({n:d['metrics']['dev'] for n,d in summary['candidates'].items()},indent=2),flush=True)

if __name__=='__main__':main()
