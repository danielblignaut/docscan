#!/usr/bin/env python3
"""DLC bounded real-capture training, independent calibration, frozen DEV report.

The source's `or` is a first capture of a laminated mock specimen, not an issuer-
verified authentic ID. The fitted heads detect screen recapture/grayscale copies.
"""
from __future__ import annotations
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[key]='1'
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image
from detector import FEATURES, VERSION, extract, extract_patch, score, decide
from receipts import verify as verify_receipts, verify_notice_registry
from study import HERE, digest, write, private_dir, source_hashes, train, evaluate, safe_path, cohort_counts


def quad_for(path, frame):
    data=json.loads(path.read_text())
    candidates=[e for e in data['_via_img_metadata'].values() if e['filename']==frame]
    if len(candidates)!=1: raise ValueError('frame annotation missing or duplicated')
    polygons=[r['shape_attributes'] for r in candidates[0]['regions'] if r.get('region_attributes',{}).get('field_name')=='doc_quad']
    if len(polygons)!=1: raise ValueError('document quadrilateral missing or duplicated')
    a=polygons[0]
    return list(map(list,zip(a['all_points_x'],a['all_points_y'])))


def verify_partition(records):
    seen={k:{} for k in ('identity_group','specimen','capture')}
    ids=set()
    for r in records:
        if r['split'] not in ('train','calibration','dev') or r['id'] in ids:
            raise ValueError('bad split or duplicate item')
        ids.add(r['id'])
        for key,owners in seen.items():
            # Calibration is within the TRAIN device; identities never overlap.
            partition='train' if key=='capture' and r['split']=='calibration' else r['split']
            if r[key] in owners and owners[r[key]]!=partition: raise ValueError('partition leak '+key)
            owners[r[key]]=partition
        if r['label']=='screen_recapture':
            allowed=['philips','macbook pro'] if r['split']=='dev' else ['lenovo']
            if r['condition'] not in allowed: raise ValueError('display-device leak')
    hashes={}
    for r in records:
        if r.get('sha256'):
            previous=hashes.setdefault(r['sha256'],r['split'])
            if previous!=r['split']: raise ValueError('identical image across split')


def source_patch_features(rgb, author_xy):
    # The immutable acquisition schema called these coordinates "centre".
    # Author screen_train.py proves they are LEFT/TOP. Preserve the exact
    # source rows and convert explicitly to the detector API's true centre.
    return extract_patch(rgb, np.asarray(author_xy, dtype=float)+112)


def load_features(data_root, records):
    rows=[]
    for i,r in enumerate(records):
        start=time.monotonic()
        row=dict(id=r['id'],global_features=None,context_features=None,error=None,context_error=None)
        try:
            if r['acquisition_error']: raise ValueError('acquisition failed: '+r['acquisition_error'])
            path=safe_path(data_root,r['path'])
            if digest(path)!=r['sha256']: raise ValueError('input hash changed')
            with Image.open(path) as im: rgb=np.asarray(im.convert('RGB'))
            row['global_features']=None
            try:
                if r['annotation_error']: raise ValueError('annotation acquisition failed')
                row['context_features']=source_patch_features(rgb,r['centre']).tolist()
                row['global_features']=row['context_features']
            except Exception as exc: row['context_error']=type(exc).__name__+': '+str(exc)
        except Exception as exc: row['error']=type(exc).__name__+': '+str(exc)
        row['seconds']=time.monotonic()-start; rows.append(row)
        if (i+1)%40==0: print(f'DLC features {i+1}/{len(records)}',flush=True)
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();os.umask(0o077);root=private_dir(args.output)
    config=json.loads((HERE/'protocol.json').read_text())
    # All feature definitions and candidates predeclared; source/device selection
    # was frozen in the import before any media download or model inference.
    config['candidates']=[c for c in config['candidates'] if c!='boundary_context']
    sources=source_hashes();manifest=verify_receipts(args.data)
    if manifest.get('source_train_only') is not True:
        raise ValueError('source-TRAIN-only manifest required; quarantined v1 forbidden')
    records=manifest['records'];verify_partition(records);verify_notice_registry(args.data)
    for r in records: r['identity']=r['identity_group'];r['device']=r['capture']
    annotation_hashes={}
    freeze=dict(author_coordinate_semantics='left_top; API centre = source xy + 112',author_crop_reference_sha256=digest(HERE/'author-crop-notice.json'),sealed_manifest_sha256=digest(args.data/'sealed-manifest.json'),timestamp=datetime.now(timezone.utc).isoformat(),config=config,sources=sources,
                manifest_sha256=digest(args.data/'manifest.json'),policy_sha256=manifest['policy_sha256'],
                members_sha256=manifest['members_sha256'],annotation_hashes=annotation_hashes,
                cohort=cohort_counts(records),frozen_counts={s:sum(r['split']==s for r in records) for s in ('train','calibration','dev')})
    write(root/'freeze.json',freeze)
    print('FROZEN DLC',freeze['frozen_counts'],flush=True)
    rows=load_features(args.data,records);write(root/'features.json',rows)
    # Train and freeze every model BEFORE evaluating any candidate on DEV.
    models={};training_failures={}
    for candidate in config['candidates']:
        if candidate=='constant_unknown': models[candidate]=None;continue
        try:
            model=train(config,records,rows,candidate)
            model.update(scope='DLC_source_TRAIN_screen_recapture_vs_MIDV_laminated_mock_patch',
                         input_protocol='author_center_224', supported_copy_kinds=['screen'],
                         deployment_validated=False,
                         training_data_license='CC-BY-SA-2.5; authors + Generated Photos attribution',
                         weights_license='Research only pending derivative-weight redistribution review; no imported pretrained weights',
                         provenance=dict(sources=sources,freeze_sha256=digest(root/'freeze.json')))
            write(root/(candidate+'.model.json'),model);models[candidate]=model
        except ValueError as exc:
            # Failed candidates remain full-denominator constant abstention arms.
            models[candidate]=None;training_failures[candidate]=str(exc)
    model_hashes={c:digest(root/(c+'.model.json')) for c,m in models.items() if m}
    write(root/'models-frozen.json',dict(models=model_hashes,training_failures=training_failures))
    summary=dict(cohort=cohort_counts(records),schema=1,kind='bounded_real_DLC_capture_pilot',data_manifest_sha256=freeze['manifest_sha256'],
                 freeze_sha256=digest(root/'freeze.json'),sources=sources,candidates={},
                 training_failures=training_failures,real_attack_examples=sum(r['label']!='bona_fide_capture' for r in records),
                 source_license=manifest['license'],network_bytes=manifest['network_bytes'],test_access=False,
                 production_promotion=False,notes=['All models use author-annotated 224x224 document patches; no automatic localization',
                 'Device split is capture phone and screen model; no print positives',
                 'Actual available cohort counts are derived from sealed rows; planned IDs do not imply availability',
                 'Calibration shares TRAIN capture device but no identity/specimen',
                 'No real print-copy positives; no issuer authenticity claims'])
    all_predictions={}
    for candidate,model in models.items():
        aggs={}
        for split in ('calibration','dev'):
            aggregate,predictions=evaluate(model,records,rows,split)
            if candidate in training_failures:
                aggregate['model_training_failure']=training_failures[candidate]
                aggregate['failures']=aggregate['items']
                for row in predictions: row.update(failure=True,reason='model_training_failure')
            # Conservative grouping by template number as an extra dependence audit.
            subset=[r for r in records if r['split']==split]
            neg=[(r,p) for r,p in zip(subset,predictions) if r['label']=='bona_fide_capture']
            groups={r['identity_group'] for r,p in neg};bad={r['identity_group'] for r,p in neg if p['status']=='copy_indicated'}
            aggregate['identity_number_groups']=len(groups)
            aggregate['false_positive_identity_number_groups']=len(bad)
            aggregate['zero_error_identity_group_upper95']=1-.05**(1/len(groups)) if groups and not bad else None
            # Keep type-level false warning/miss counts; no averaged-away regression.
            aggregate['by_document_type']={t:dict(items=sum(r['type']==t for r in subset),
                negative_items=sum(r['type']==t and r['label']=='bona_fide_capture' for r in subset),
                attack_items=sum(r['type']==t and r['label']!='bona_fide_capture' for r in subset),
                false_positives=sum(r['type']==t and r['label']=='bona_fide_capture' and p['status']=='copy_indicated' for r,p in zip(subset,predictions)),
                detected_attacks=sum(r['type']==t and r['label']!='bona_fide_capture' and p['status']=='copy_indicated' for r,p in zip(subset,predictions))) for t in sorted({r['type'] for r in subset})}
            aggs[split]=aggregate;all_predictions[(candidate,split)]=predictions
            write(root/(candidate+'.'+split+'.predictions.json'),predictions)
        summary['candidates'][candidate]=dict(metrics=aggs,model_sha256=model_hashes.get(candidate),
                                             thresholds=model['thresholds'] if model else None)
    # Pairwise gains and regressions among all candidates, not just the winner.
    summary['pairwise_dev']={}
    labels=[r['label'] for r in records if r['split']=='dev']
    for a in config['candidates']:
        for b in config['candidates']:
            if a>=b: continue
            aa=all_predictions[(a,'dev')];bb=all_predictions[(b,'dev')]
            summary['pairwise_dev'][a+' -> '+b]=dict(
                new_false_positives=sum(l=='bona_fide_capture' and x['status']!='copy_indicated' and y['status']=='copy_indicated' for l,x,y in zip(labels,aa,bb)),
                removed_false_positives=sum(l=='bona_fide_capture' and x['status']=='copy_indicated' and y['status']!='copy_indicated' for l,x,y in zip(labels,aa,bb)),
                lost_detections=sum(l!='bona_fide_capture' and x['status']=='copy_indicated' and y['status']!='copy_indicated' for l,x,y in zip(labels,aa,bb)),
                gained_detections=sum(l!='bona_fide_capture' and x['status']!='copy_indicated' and y['status']=='copy_indicated' for l,x,y in zip(labels,aa,bb)))
    if source_hashes()!=sources: raise ValueError('source changed during run')
    if digest(args.data/'manifest.json')!=freeze['manifest_sha256']: raise ValueError('manifest changed')
    for path,sha in annotation_hashes.items():
        if digest(safe_path(args.data,path))!=sha: raise ValueError('annotation changed')
    for r in records:
        if not r['acquisition_error'] and digest(safe_path(args.data,r['path']))!=r['sha256']: raise ValueError('image changed')
    verify_receipts(args.data);verify_notice_registry(args.data)
    if digest(args.data/'sealed-manifest.json')!=freeze['sealed_manifest_sha256']:raise ValueError('sealed manifest changed')
    write(root/'summary.json',summary)
    print(json.dumps({c:{s:{k:v for k,v in a.items() if k not in ('by_condition','by_document_type')} for s,a in d['metrics'].items()} for c,d in summary['candidates'].items()},indent=2),flush=True)

if __name__=='__main__': main()
