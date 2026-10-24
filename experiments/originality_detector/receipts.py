"""Seal and verify source-TRAIN import provenance before touching any image."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
from fetch_dlc import Network, write
from fetch_train_only import train_lists

FIELDS=('id','source','source_member','type','number','clip','split','capture','display','centre','label','specimen','identity_group')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def within(root,relative):
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('receipt path escapes root')
    return path


def seal(root):
    """Append a sealed manifest without overwriting acquisition receipts.

    Source TRAIN lists are re-downloaded and must match the pre-download hashes.
    This also upgrades in-flight v2 imports whose original downloader predates
    receipt binding. Every original receipt/source snapshot remains unchanged.
    """
    root=root.resolve();os.umask(0o077)
    manifest=json.loads((root/'manifest.json').read_text())
    selection=json.loads((root/'selection-frozen.json').read_text())
    # Replay the primary notice/list bytes; their original hashes are authoritative.
    net=Network();lists=train_lists(net,save_root=root/'source-train-lists')
    if {k:v[1] for k,v in lists.items()}!=selection['list_hashes']:
        raise ValueError('author TRAIN lists changed since selection')
    links={name:sha(root/name) for name in ('manifest.json','policy.json','selection-frozen.json','members-frozen.json',
           'midv2020-readme.txt','midv2020-license.txt','dlc-license.txt')}
    for name in lists:links['source-train-lists/'+name]=sha(root/'source-train-lists'/name)
    # Exact executed acquisition source is preserved, even after fixing helpers.
    for name in ('fetch_train_only.py','fetch_dlc.py'):
        p=root/(name+'.acquisition-source')
        if not p.exists():raise ValueError('executed acquisition source missing')
        links[p.name]=sha(p)
    policy=json.loads((root/'policy.json').read_text())
    if sha(root/'fetch_train_only.py.acquisition-source')!=policy['code_sha256']:
        raise ValueError('acquisition code hash mismatch')
    sealed=dict(schema=1,source_train_only=True,linked_receipts=links,acquisition_manifest=manifest,
                sealer_sha256=sha(Path(__file__)),source_list_replay_network_bytes=net.bytes)
    # Validate exact rows before writing a seal, not after decoding any media.
    verify(root,sealed)
    write(root/'sealed-manifest.json',sealed)
    return sealed


def verify(root,sealed=None):
    root=root.resolve()
    if sealed is None:sealed=json.loads((root/'sealed-manifest.json').read_text())
    if sealed.get('source_train_only') is not True:raise ValueError('not source TRAIN')
    links=sealed['linked_receipts']
    required={'manifest.json','policy.json','selection-frozen.json','members-frozen.json',
              'midv2020-readme.txt','midv2020-license.txt','dlc-license.txt',
              'source-train-lists/screen_positive_train.lst','source-train-lists/screen_negative_train.lst',
              'fetch_train_only.py.acquisition-source','fetch_dlc.py.acquisition-source'}
    if not required.issubset(links):raise ValueError('missing linked receipt')
    for name,digest in links.items():
        if sha(within(root,name))!=digest:raise ValueError('linked receipt changed: '+name)
    original=json.loads((root/'manifest.json').read_text())
    if original!=sealed['acquisition_manifest']:raise ValueError('embedded acquisition manifest changed')
    if original['policy_sha256']!=links['policy.json'] or original['members_sha256']!=links['members-frozen.json']:
        raise ValueError('acquisition receipt hash mismatch')
    selection=json.loads((root/'selection-frozen.json').read_text())
    for name,digest in selection['list_hashes'].items():
        if sha(within(root,'source-train-lists/'+name))!=digest:raise ValueError('TRAIN-list hash mismatch')
    policy=json.loads((root/'policy.json').read_text())
    if links['fetch_train_only.py.acquisition-source']!=policy['code_sha256']:raise ValueError('source hash mismatch')
    lists={}
    for name in ('screen_positive_train.lst','screen_negative_train.lst'):
        table={}
        for line in (root/'source-train-lists'/name).read_text().splitlines():
            member,x,y=line.split();table[member.lstrip('/')]=[float(x),float(y)]
        lists[name]=table
    planned=selection['records'];actual=original['records']
    if len(planned)!=len(actual) or len({r['id'] for r in planned})!=len(planned):raise ValueError('denominator/duplicate mismatch')
    members=json.loads((root/'members-frozen.json').read_text())['members']
    for p,r in zip(planned,actual):
        if any(p.get(k)!=r.get(k) for k in FIELDS):raise ValueError('selected row/centre/split changed')
        if r['type'] not in policy['types'] or r['split'] not in ('train','calibration','dev'):raise ValueError('forbidden type/split')
        if r['source_member'] not in lists['screen_positive_train.lst' if r['source']=='dlc' else 'screen_negative_train.lst']:
            raise ValueError('image absent from author TRAIN list')
        table=lists['screen_positive_train.lst' if r['source']=='dlc' else 'screen_negative_train.lst']
        if r['centre']!=table[r['source_member']]:raise ValueError('centre differs from author TRAIN row')
        spec=policy['positive_specimens' if r['source']=='dlc' else 'negative_specimens']
        if r['number'] not in spec[r['split']]:raise ValueError('specimen assignment differs from policy')
        if r['capture']!=('iphone' if r['split']=='dev' else 'android'):raise ValueError('capture device differs')
        if r['source']=='dlc' and r['display'] not in policy['displays'][r['split']]:raise ValueError('display assignment differs')
        expected_label='screen_recapture' if r['source']=='dlc' else 'bona_fide_capture'
        if r['label']!=expected_label:raise ValueError('label differs')
        if r['path']!='media/'+r['id']:raise ValueError('image path differs')
        entry=members.get(r['id'])
        if not entry or not entry['name'].endswith('/'+r['source_member']):raise ValueError('archive member differs')
    return original


def verify_notice_registry(root):
    registry=json.loads((Path(__file__).parent/'source-notices.json').read_text())
    expected={x['url']:x.get('sha256') for x in registry['sources']}
    for filename,url in [('midv2020-readme.txt','ftp://smartengines.com/midv-2020/readme.txt'),
                         ('midv2020-license.txt','ftp://smartengines.com/midv-2020/license.txt')]:
        if not expected.get(url) or sha(root/filename)!=expected[url]:
            raise ValueError('notice differs from pinned primary-source registry')



if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('--seal',action='store_true')
    a=p.parse_args();(seal if a.seal else verify)(a.root);print('receipt verification passed')
