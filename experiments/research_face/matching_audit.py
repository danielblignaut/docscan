#!/usr/bin/env python3
"""Read-only independent accounting of retained matching-v1 artifacts.

No inference, threshold fitting, image display or identity output. The audit
checks score matrices against their embedding and identity correspondence and
reconstructs the candidate from all three native views in float64.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
import numpy as np

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_native(receipt):
    files = receipt['output_hashes']
    for path, expected in files.items():
        assert digest(path) == expected, 'Native artifact hash changed'
    binaries = sorted(Path(p) for p in files if p.endswith('.f32'))
    paths = (binaries[0].parent / 'images.txt').read_text().splitlines()
    vectors, found = [], []
    for path in binaries:
        meta = json.loads(Path(str(path)+'.json').read_text())
        values = np.fromfile(path,dtype='<f4').reshape(len(meta['items']),meta['dim']).astype(np.float64)
        norms = np.linalg.norm(values,axis=1)
        mask = np.array([x['found'] and np.isfinite(x.get('presence',1.)) and x.get('presence',1.) >= .5 for x in meta['items']])
        mask &= np.isfinite(values).all(axis=1) & np.isfinite(norms) & (norms > 1e-12)
        values[~mask] = 0
        values /= np.where(mask,norms,1)[:,None]
        vectors.extend(values)
        found.extend(mask)
    assert len(paths) == len(vectors) == len(set(paths)), 'Native path/row correspondence'
    return {p:(v,bool(f)) for p,v,f in zip(paths,vectors,found,strict=True)}


def audit(report_path):
    report = json.loads(report_path.read_text())
    private = report['private_artifacts']
    for path, expected in private.items():
        assert digest(path) == expected, 'Private artifact hash changed'
    for path, expected in report['freeze']['inputs'].items():
        assert digest(path) == expected, 'Frozen input changed'
    for name, expected in report['freeze']['models'].items():
        assert digest(HERE.parents[1]/'models/face'/name) == expected, 'Model changed'
    assert report['freeze']['build_receipt']['binary_sha256'] == report['freeze']['binary_sha256']
    folder = Path(next(iter(private))).parent
    assert digest(folder/'freeze.json') == report['freeze_sha256']
    assert folder.stat().st_mode & 0o077 == 0, 'Private directory exposed'
    for path in folder.rglob('*'):
        assert path.stat().st_mode & 0o077 == 0, 'Private file exposed'
    rows = json.loads((folder/'rows.json').read_text())
    all_rows = json.loads((folder/'all_inference_rows.json').read_text())
    for row in all_rows:
        assert digest(row['path']) == row['sha256'], 'Image input changed'
    probes = [r for r in rows if r['pose']=='neutral']
    refs = [r for r in rows if r['pose']=='smile']
    ids = {split:{r['id'] for r in refs if r['split']==split} for split in ('calibration','validation')}
    assert len(ids['calibration']) == len(ids['validation']) == 51
    assert ids['calibration'].isdisjoint(ids['validation'])
    ordered = sorted(ids['calibration']|ids['validation'],key=lambda x:hashlib.sha256(('london-dev-v1:'+x).encode()).hexdigest())
    assert set(ordered[:51]) == ids['calibration']
    assert set(ordered[51:]) == ids['validation']
    stored = np.load(folder/'embeddings.npz',allow_pickle=False)
    scores = np.load(folder/'pair_scores.npz',allow_pickle=False)
    native = report['inference']
    base = load_native(native['baseline_old_conditions']) | load_native(native['baseline_hard96'])
    live = load_native(native['references'])
    gamma = [load_native(item) for item in native['gamma_views']]
    gamma_rows = [all_rows[len(rows)+i*len(probes):len(rows)+(i+1)*len(probes)] for i in range(2)]
    view_missing = {}
    for i,row in enumerate(probes):
        values, flags = [base[row['path']][0]], [base[row['path']][1]]
        for j in range(2):
            gr = gamma_rows[j][i]
            assert all(gr[k]==row[k] for k in ('id','split','pose','condition'))
            value, flag = gamma[j][gr['path']]
            values.append(value); flags.append(flag)
            group=f"{row['condition']}/{row['split']}/gamma{native['gamma_views'][j]['gamma']}"
            view_missing[group]=view_missing.get(group,0)+int(not flag)
        np.testing.assert_allclose(stored['baseline'][i],values[0],atol=2e-7)
        assert bool(stored['baseline_found'][i]) == flags[0]
        mean = np.mean(values,axis=0)
        norm = np.linalg.norm(mean)
        usable = all(flags) and np.isfinite(norm) and norm > 1e-12
        expected = mean/norm if usable else np.zeros_like(mean)
        assert bool(stored['gamma_found'][i]) == usable
        np.testing.assert_allclose(stored['gamma_mean'][i],expected,atol=2e-7)
    for i,row in enumerate(refs):
        v,f=live[row['path']]
        np.testing.assert_allclose(stored['references'][i],v,atol=2e-7)
        assert bool(stored['references_found'][i]) == f
    cells=0
    for condition, splits in report['metrics'].items():
        for split, entry in splits.items():
            pi=[i for i,r in enumerate(probes) if r['condition']==condition and r['split']==split]
            ri=[i for i,r in enumerate(refs) if r['split']==split]
            key=f'{condition}_{split}'
            np.testing.assert_array_equal(scores[key+'_probe_ids'],[probes[i]['id'] for i in pi])
            np.testing.assert_array_equal(scores[key+'_reference_ids'],[refs[i]['id'] for i in ri])
            labels=np.equal.outer(scores[key+'_probe_ids'],scores[key+'_reference_ids'])
            np.testing.assert_array_equal(scores[key+'_labels'],labels)
            assert labels.sum()==entry['genuine_pairs']==51
            assert (~labels).sum()==entry['impostor_pairs']==2550
            for arm, flag_name in [('baseline','baseline_found'),('gamma_mean','gamma_found')]:
                matrix=stored[arm][pi] @ stored['references'][ri].T
                matrix[~(stored[flag_name][pi,None]&stored['references_found'][None,ri])]=-np.inf
                np.testing.assert_array_equal(matrix,scores[key+'_'+arm])
                for point, rates in entry['operating_points'].items():
                    threshold={'document':.356,'live':.366}[point]
                    result=rates[arm]
                    assert result['threshold']==threshold
                    accepted=np.isfinite(matrix)&(matrix>=threshold)
                    assert int(accepted[labels].sum())==result['genuine_accepted']
                    assert int(accepted[~labels].sum())==result['impostors_accepted']
                    assert result['tar']==int(accepted[labels].sum())/51
                    assert result['far']==int(accepted[~labels].sum())/2550
                    cells+=1
    return dict(report_sha256=digest(report_path),audit_sha256=digest(Path(__file__)),status='passed',
                identities=102,original_source_captures=204,document_conditions=4,candidates_including_baseline=2,
                scoring_cells_at_two_thresholds=cells,pairs_per_cell=2601,unique_comparisons_per_arm=20808,
                inference_rows_including_reused=1326,fresh_native_rows=918,reused_corresponding_rows=408,
                gamma_missing_views=view_missing,
                checks=['all frozen/native/image/score hashes','owner-private permissions','identity-disjoint original split',
                        'native-to-view-to-identity correspondence','float64 unit normalization and equal aggregation',
                        'every retained pair matrix and all 32 TAR/FAR cells','original rows remain in denominators'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=HERE/'results/matching_photometric_v1.json')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=audit(args.report)
    if args.output:
        assert args.output.parent.resolve()==(HERE/'results').resolve() and args.output.name.startswith('matching_')
        with args.output.open('x') as out:
            json.dump(result,out,indent=2);out.write('\n')
    print(json.dumps(result,indent=2))
