#!/usr/bin/env python3
"""DLC source-TRAIN-only screen patch import; fresh receipt, quarantined v1 unused.

Positive images must appear in screen_positive_train.lst; negative images must
appear in screen_negative_train.lst. No source TEST lists/pixels/truth are read.
MIDV's uncompressed tar is indexed using 512-byte header reads and FTP REST,
skipping every unselected payload. Only TRAIN-list-selected pixels are fetched.
"""
import argparse
import csv
from datetime import datetime, timezone
import ftplib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import urllib.request
import zipfile
from fetch_dlc import Network, RemoteZip, write

TYPES=('esp_id','rus_internalpassport')


class BaselineReader(io.RawIOBase):
    def __init__(self,net): self.net=net;self.pos=0;self.size=88403129
    def tell(self): return self.pos
    def seek(self,o,w=0): self.pos=o if w==0 else self.pos+o if w==1 else self.size+o;return self.pos
    def read(self,n=-1):
        n=min(n if n>=0 else self.size,self.size-self.pos)
        if n<=0:return b''
        d=self.net.get('https://zenodo.org/records/6792397/files/experimental_baseline.zip?download=1',self.pos,n)
        self.pos+=len(d);return d


def train_lists(net, save_root=None):
    result={}
    with zipfile.ZipFile(BaselineReader(net)) as z:
        for name in ('screen_positive_train.lst','screen_negative_train.lst'):
            raw=z.read(name)
            if save_root is not None:
                save_root.mkdir(mode=0o700, parents=True, exist_ok=True)
                with (save_root/name).open('xb') as f: f.write(raw)
            rows={}
            for line in raw.decode().splitlines():
                path,x,y=line.split();path=path.lstrip('/')
                typ=path.split('/')[0]
                if typ not in TYPES:continue
                rows[path]=[float(x),float(y)]
            result[name]=(rows,hashlib.sha256(raw).hexdigest())
    return result


class FTPRange:
    def __init__(self):self.bytes=0;self.requests=0
    def get(self,path,start,size):
        if size>32*1024**2 or self.bytes+size>800*1024**2:raise ValueError('FTP byte budget')
        f=ftplib.FTP('smartengines.com',timeout=30);f.login();f.voidcmd('TYPE I');self.requests+=1
        try:
            with f.transfercmd('RETR '+path,rest=start) as sock:
                chunks=[];left=size
                while left:
                    b=sock.recv(min(left,1<<20))
                    if not b:raise EOFError('short FTP range')
                    chunks.append(b);left-=len(b);self.bytes+=len(b)
            return b''.join(chunks)
        finally:f.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--reuse-import',type=Path)
    args=p.parse_args();root=args.output.resolve();os.umask(0o077)
    if root.is_relative_to(Path(__file__).resolve().parents[2]):raise ValueError('outside git required')
    root.mkdir(mode=0o700,parents=True,exist_ok=False);net=Network();ftp=FTPRange()
    policy=dict(timestamp=datetime.now(timezone.utc).isoformat(),source='author screen TRAIN lists only',types=TYPES,
        positive_specimens={'train':[0,1,2,3],'calibration':[],'dev':[4,5,6,7]},
        negative_specimens={'train':[20,21,30,31,50,51,60,61],'calibration':[40,41,90,91],
                           'dev':[25,26,35,36,45,46,55,56,65,66,95,96]},
        positive_capture={'train':'android','calibration':'android','dev':'iphone'},
        displays={'train':['lenovo'],'calibration':['lenovo'],'dev':['philips','macbook pro']},
        frames_per_clip=2,positive_clips_per_specimen=2,
        note='Two chronologically spread author-labelled TRAIN frames per clip; no TEST list loaded',
        maximum_total_bytes=1024**3,code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    write(root/'policy.json',policy)
    for name in ('fetch_train_only.py','fetch_dlc.py'):
        (root/(name+'.acquisition-source')).write_bytes((Path(__file__).parent/name).read_bytes())
    lists=train_lists(net,save_root=root/'initial-train-lists')
    for name in ('readme.txt','license.txt'):
        (root/('midv2020-'+name)).write_bytes(urllib.request.urlopen('ftp://smartengines.com/midv-2020/'+name,timeout=30).read(20000))
    (root/'dlc-license.txt').write_bytes(net.get('https://zenodo.org/records/6792397/files/license.txt?download=1',cap=20000))
    metadata=net.get('https://zenodo.org/records/6792397/files/dlc-2021.csv?download=1',cap=80000)
    eligible=[]
    for path,device,display in csv.reader(io.StringIO(metadata.decode()),delimiter=';'):
        typ,clip=path.split('/')
        if typ not in TYPES or '.re' not in clip:continue
        number=int(clip[:2]);split=next((s for s,ns in policy['positive_specimens'].items() if number in ns),None)
        if not split or device!=policy['positive_capture'][split] or display not in policy['displays'][split]:continue
        eligible.append(dict(type=typ,clip=clip,number=number,split=split,capture=device,display=display))
    selection=[];clips={}
    for e in sorted(eligible,key=lambda e:(e['type'],e['clip'])):
        key=(e['type'],e['number']);clips.setdefault(key,[])
        if len(clips[key])>=policy['positive_clips_per_specimen']:continue
        prefix=e['type']+'/'+e['clip']+'/'
        members=sorted(k for k in lists['screen_positive_train.lst'][0] if k.startswith(prefix))
        if len(members)<2:
            continue
        clips[key].append(e)
        for member in (members[0],members[len(members)//2]):
            selection.append(dict(**e,id='dlc-'+member.replace('/','-'),source='dlc',source_member=member,
                centre=lists['screen_positive_train.lst'][0][member],label='screen_recapture',
                specimen=e['type']+'-'+str(e['number']),identity_group=e['type']+'-'+str(e['number'])))
    for typ in TYPES:
        for split,numbers in policy['negative_specimens'].items():
            for number in numbers:
                prefix=f'{typ}/{number:02}/'
                members=sorted(k for k in lists['screen_negative_train.lst'][0] if k.startswith(prefix))
                if len(members)<2:continue
                for member in (members[0],members[len(members)//2]):
                    selection.append(dict(id='midv-'+member.replace('/','-'),source='midv',source_member=member,
                        type=typ,number=number,clip=f'{number:02}',split=split,
                        capture='iphone' if split=='dev' else 'android',display=None,
                        centre=lists['screen_negative_train.lst'][0][member],label='bona_fide_capture',
                        specimen=typ+'-'+str(number),identity_group=typ+'-'+str(number)))
    # Before any image access, validate membership and identity/device isolation.
    for r in selection:
        table=lists['screen_positive_train.lst' if r['source']=='dlc' else 'screen_negative_train.lst'][0]
        if r['source_member'] not in table:raise ValueError('not author TRAIN')
    write(root/'selection-frozen.json',dict(records=selection,skipped_positive_clips=[e for e in eligible if not any(r['source']=='dlc' and r['type']==e['type'] and r['clip']==e['clip'] for r in selection)],list_hashes={k:v[1] for k,v in lists.items()},
                    metadata_sha256=hashlib.sha256(metadata).hexdigest()))
    print('frozen',len(selection),'items',flush=True)
    archive=RemoteZip(net,'6466770','re')
    entries=archive.directory({(r['type'],r['clip']) for r in selection if r['source']=='dlc'})
    mapped={}
    for r in selection:
        if r['source']=='dlc':
            hit=[e for e in entries if e['kind']=='image' and e['name'].endswith('/'+r['source_member'])]
            if len(hit)!=1:raise ValueError('TRAIN member missing from ZIP')
            mapped[r['id']]=hit[0]
    # Uncompressed TAR: read headers, skip payloads. No broad archive download.
    desired={'images/'+r['source_member']:r['id'] for r in selection if r['source']=='midv'}
    reuse_rows={};reuse_root=None
    if args.reuse_import:
        from receipts import verify
        reuse_root=args.reuse_import.resolve()
        prior=verify(reuse_root)
        old_members=json.loads((reuse_root/'members-frozen.json').read_text())['members']
        by_member={r['source_member']:r for r in prior['records'] if r['source']=='midv' and not r['acquisition_error']}
        for name,item_id in list(desired.items()):
            member=name.removeprefix('images/')
            if member not in by_member:continue
            previous=by_member[member]
            current=next(r for r in selection if r['id']==item_id)
            if any(previous[k]!=current[k] for k in ('centre','split','capture','specimen','label')):
                raise ValueError('reused TRAIN row differs')
            mapped[item_id]=old_members[item_id];reuse_rows[item_id]=previous;del desired[name]
    offset=0;headers=0;archive_path='/midv-2020/dataset/clips.tar'
    while desired:
        raw=ftp.get(archive_path,offset,512);headers+=1
        if raw==b'\0'*512:break
        info=tarfile.TarInfo.frombuf(raw,'utf-8','surrogateescape')
        name=info.name.lstrip('./')
        if info.type in (tarfile.GNUTYPE_LONGNAME,tarfile.XHDTYPE,tarfile.XGLTYPE):
            raise ValueError('extended tar headers require separate audited parser')
        if name in desired:
            item=desired.pop(name);mapped[item]=dict(offset=offset+512,size=info.size,name=name)
        offset+=512+((info.size+511)//512)*512
        if headers%5000==0:print('TAR metadata headers',headers,'remaining authorized images',len(desired),flush=True)
    if desired:raise ValueError('TRAIN members missing from TAR')
    estimate=sum(e.get('compressed',e['size']) for e in mapped.values())
    write(root/'members-frozen.json',dict(members=mapped,estimated_media_bytes=estimate,tar_header_count=headers,
                                        metadata_bytes=net.bytes+ftp.bytes,reused_import_seal_sha256=hashlib.sha256((reuse_root/'sealed-manifest.json').read_bytes()).hexdigest() if reuse_root else None))
    if net.bytes+ftp.bytes+estimate>1024**3:raise ValueError('total exceeds budget')
    print('estimated media bytes',estimate,flush=True)
    (root/'media').mkdir(mode=0o700)
    records=[]
    for i,r in enumerate(selection):
        r=dict(r);e=mapped[r['id']];r['path']='media/'+r['id'];r['annotation_error']=None
        r['condition']=r['display'] or 'first_capture'
        try:
            if r['id'] in reuse_rows:
                old=reuse_rows[r['id']];old_path=(reuse_root/old['path']).resolve()
                if not old_path.is_relative_to(reuse_root):raise ValueError('reuse path escape')
                raw=old_path.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=old['sha256']:raise ValueError('reused image changed')
            else:
                raw=archive.member(e) if r['source']=='dlc' else ftp.get(archive_path,e['offset'],e['size'])
            (root/r['path']).write_bytes(raw)
            r.update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),acquisition_error=None)
        except Exception as exc:r.update(sha256=None,acquisition_error=type(exc).__name__+': '+str(exc))
        records.append(r)
        # Incremental receipt survives interrupts without disguising access.
        with (root/'acquisition.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
        if (i+1)%20==0:print('media',i+1,'/',len(selection),flush=True)
    write(root/'manifest.json',dict(records=records,network_bytes=net.bytes+ftp.bytes,
        policy_sha256=hashlib.sha256((root/'policy.json').read_bytes()).hexdigest(),
        members_sha256=hashlib.sha256((root/'members-frozen.json').read_bytes()).hexdigest(),
        license='CC-BY-SA-2.5; Polevoy et al., Bulatov et al.; Generated Photos attribution',source_train_only=True))
    print('complete',len(records),net.bytes+ftp.bytes,flush=True)

if __name__=='__main__':main()
