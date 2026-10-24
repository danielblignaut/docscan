#!/usr/bin/env python3
"""Bounded author-Zenodo ZIP range import, no unselected media/truth downloaded.

Archive DIRECTORY metadata is inspected only to locate predeclared TRAIN/DEV
clips. No local bench TEST files or source author-designated TEST files are used.
Separate specimen-number blocks and capture/display devices before any inference.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import time
import urllib.request
import zlib

HERE = Path(__file__).resolve().parent
TYPES = ('alb_id', 'aze_passport', 'esp_id', 'est_id', 'fin_id', 'rus_internalpassport')
RECORDS = {'or': '6792397', 'cg': '6792397', 're': '6466770'}
CAP = 1024**3


def write(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False); f.write('\n')


class Network:
    def __init__(self):
        self.bytes = 0
        self.requests = 0

    def get(self, url, start=None, length=None, cap=2_000_000):
        headers = {'User-Agent': 'docscan-research-bounded-import/1.0'}
        if start is not None:
            headers['Range'] = f'bytes={start}-{start+length-1}'
            cap = length
        if cap > 64*1024**2 or self.bytes+cap > CAP:
            raise ValueError('download budget exceeded')
        for attempt in range(3):
            try:
                self.requests += 1
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=40) as r:
                    if start is not None and (r.status != 206 or not r.headers.get('Content-Range', '').startswith(f'bytes {start}-{start+length-1}/')):
                        raise ValueError('server did not honor exact byte range')
                    data = r.read(cap+1)
                    self.bytes += len(data)
                    if len(data)>cap or start is not None and len(data)!=length:
                        raise ValueError('unexpected response size')
                    return data
            except (OSError, TimeoutError):
                if attempt==2: raise
                time.sleep(attempt+1)
        raise RuntimeError('unreachable')


class RemoteZip:
    def __init__(self, net, record, stem):
        self.net = net
        raw = net.get('https://zenodo.org/api/records/'+record)
        meta = json.loads(raw)
        if meta['metadata'].get('license',{}).get('id') != 'cc-by-sa-2.5':
            raise ValueError('unexpected dataset rights')
        files = {f['key']: f for f in meta['files']}
        self.metadata_sha256 = hashlib.sha256(raw).hexdigest()
        self.parts = []
        for name in sorted(n for n in files if n.startswith(stem+'.z') and n != stem+'.zip')+[stem+'.zip']:
            entry = files[name]
            self.parts.append(dict(name=name, size=entry['size'], url=f'https://zenodo.org/records/{record}/files/{name}?download=1'))
        self.total_archive_bytes = sum(p['size'] for p in self.parts)

    def read(self, disk, offset, length):
        data = bytearray()
        while length:
            p = self.parts[disk]
            take = min(length, p['size']-offset)
            if take <= 0: raise ValueError('invalid archive offset')
            data.extend(self.net.get(p['url'], offset, take))
            length -= take; disk += 1; offset = 0
        return bytes(data)

    def directory(self, allowed_clips):
        last = len(self.parts)-1
        # These author releases have a comment-free EOCD. Read exactly its 22
        # metadata bytes, never a speculative tail containing unselected media.
        end = self.read(last, self.parts[last]['size']-22, 22)
        sig, disk, cd_disk, n_disk, n_total, cd_len, cd_offset, comment = struct.unpack('<4s4H2IH', end)
        if sig != b'PK\x05\x06' or comment:
            raise ValueError('unsupported ZIP end record')
        if cd_len == 0xffffffff or cd_offset == 0xffffffff or n_total == 65535:
            locator = self.read(last, self.parts[last]['size']-42, 20)
            sig, disk64, offset64, disks = struct.unpack('<4sIQI', locator)
            if sig != b'PK\x06\x07': raise ValueError('ZIP64 locator missing')
            z = self.read(disk64, offset64, 56)
            fields = struct.unpack('<4sQ2H2I4Q', z)
            if fields[0] != b'PK\x06\x06': raise ValueError('ZIP64 record missing')
            cd_disk, cd_len, cd_offset = fields[5], fields[8], fields[9]
        data = self.read(cd_disk, cd_offset, cd_len)
        pos = 0; allowed = []
        while pos < len(data):
            c = struct.unpack_from('<4s6H3I5H2I', data, pos)
            if c[0] != b'PK\x01\x02': raise ValueError('invalid central directory')
            flags, method, crc, compressed, size = c[3], c[4], c[7], c[8], c[9]
            nl, el, cl, disk, offset = c[10], c[11], c[12], c[13], c[16]
            name = data[pos+46:pos+46+nl].decode('utf-8' if flags&2048 else 'cp437')
            extra = data[pos+46+nl:pos+46+nl+el]
            ep = 0
            while ep+4<=len(extra):
                tag, count = struct.unpack_from('<HH', extra, ep); ep+=4
                block=extra[ep:ep+count]; ep+=count
                if tag==1:
                    bi=0
                    values=[size,compressed,offset,disk]
                    for i in range(4):
                        if values[i]==0xffffffff or i==3 and values[i]==65535:
                            fmt='<I' if i==3 else '<Q'; values[i]=struct.unpack_from(fmt,block,bi)[0]; bi+=struct.calcsize(fmt)
                    size,compressed,offset,disk=values
            # Unselected names are never retained, printed, or used as truth.
            parts=name.replace('\\','/').split('/')
            for typ, clip in allowed_clips:
                image_match = f'/{typ}/{clip}/' in '/'+name and name.lower().endswith('.jpg')
                annotation_match = name.endswith('/'+typ+'/'+clip+'.json')
                if image_match or annotation_match:
                    allowed.append(dict(name=name, type=typ, clip=clip, method=method, crc=crc,
                                        compressed=compressed, size=size, disk=disk, offset=offset,
                                        kind='image' if image_match else 'annotation'))
                    break
            pos += 46+nl+el+cl
        return allowed

    def member(self, entry):
        if entry['size']>32*1024**2: raise ValueError('member too large')
        h=self.read(entry['disk'],entry['offset'],30)
        sig,ver,flags,method,tm,dt,crc,cs,us,nl,el=struct.unpack('<4s5H3I2H',h)
        if sig!=b'PK\x03\x04' or flags&1 or method!=entry['method']:
            raise ValueError('invalid local header')
        # Seek across split-volume boundaries before compressed payload.
        disk=entry['disk']; offset=entry['offset']+30+nl+el
        while offset>=self.parts[disk]['size']:
            offset-=self.parts[disk]['size']; disk+=1
        compressed=self.read(disk,offset,entry['compressed'])
        if method==0: raw=compressed
        elif method==8:
            decoder=zlib.decompressobj(-15)
            raw=decoder.decompress(compressed, entry['size']+1)
            if not decoder.eof or decoder.unconsumed_tail: raise ValueError('invalid compressed size')
        else: raise ValueError('unsupported compression')
        if len(raw)!=entry['size'] or zlib.crc32(raw)&0xffffffff!=entry['crc']:
            raise ValueError('member checksum mismatch')
        return raw


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); os.umask(0o077); root=args.output.resolve()
    if root.is_relative_to(HERE.parents[1]): raise ValueError('private storage outside git required')
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    net=Network()
    policy=dict(timestamp=datetime.now(timezone.utc).isoformat(), allowed_types=TYPES,
                train_specimen_numbers=[0,1,2,3], calibration_specimen_numbers=[4,5], dev_specimen_numbers=[6,7],
                train_capture='android', dev_capture='iphone', train_displays=['lenovo','macbook pro'], dev_displays=['philips'],
                kinds=['or','cg','re'], clips_per_specimen_kind=1, frame_ordinals=[0,24],
                download_cap=CAP, split_note='Calibration is TRAIN held out by specimen; capture device shared only within TRAIN/calibration, never DEV',
                code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    write(root/'policy.json',policy)
    for name in ('README.md','license.txt'):
        (root/name).write_bytes(net.get('https://zenodo.org/records/6792397/files/'+name+'?download=1',cap=20000))
    metadata=net.get('https://zenodo.org/records/6792397/files/dlc-2021.csv?download=1',cap=80000)
    chosen={}
    for row in csv.reader(io.StringIO(metadata.decode()),delimiter=';'):
        path,capture,condition=row
        typ,clip=path.split('/')
        if typ not in TYPES: continue
        number=int(clip[:2]); kind=clip[3:5]
        if number not in range(8) or kind not in RECORDS: continue
        split='train' if number<4 else 'calibration' if number<6 else 'dev'
        if capture!=('iphone' if split=='dev' else 'android'): continue
        if kind=='re' and condition not in (['philips'] if split=='dev' else ['lenovo','macbook pro']): continue
        key=(typ,number,kind)
        candidate=dict(type=typ,clip=clip,number=number,kind=kind,split=split,capture=capture,condition=condition)
        if key not in chosen or clip<chosen[key]['clip']: chosen[key]=candidate
    clips=sorted(chosen.values(),key=lambda r:(r['type'],r['clip']))
    write(root/'clips-frozen.json',dict(metadata_sha256=hashlib.sha256(metadata).hexdigest(),clips=clips))
    # Publish missing cells explicitly: no silently balanced/replaced specimens.
    missing=[dict(type=t,number=n,kind=k) for t in TYPES for n in range(8) for k in RECORDS if (t,n,k) not in chosen]
    archives={k:RemoteZip(net,record,k) for k,record in RECORDS.items()}
    selection=[]
    for kind, archive in archives.items():
        candidates=[r for r in clips if r['kind']==kind]
        entries=archive.directory({(r['type'],r['clip']) for r in candidates})
        for r in candidates:
            own=[e for e in entries if e['type']==r['type'] and e['clip']==r['clip']]
            images=sorted((e for e in own if e['kind']=='image'),key=lambda e:e['name'])
            annotations=[e for e in own if e['kind']=='annotation']
            if len(images)<25 or len(annotations)!=1:
                raise ValueError('authorized clip members missing: '+r['type']+'/'+r['clip'])
            selection.append(dict(**r,annotation=annotations[0],images=[images[i] for i in policy['frame_ordinals']]))
    estimate=sum(s['annotation']['compressed']+sum(e['compressed'] for e in s['images']) for s in selection)
    write(root/'members-frozen.json',dict(selection=selection,missing_metadata_cells=missing,
                                       compressed_media_bytes=estimate,metadata_download_bytes=net.bytes,
                                       archive_total_bytes={k:a.total_archive_bytes for k,a in archives.items()}))
    print(json.dumps(dict(clips=len(selection), images=2*len(selection), estimated_compressed_bytes=estimate,
                          metadata_bytes=net.bytes,missing_metadata_cells=len(missing))),flush=True)
    if estimate+net.bytes>CAP: raise ValueError('preflight exceeds 1 GiB budget')
    (root/'media').mkdir(mode=0o700)
    records=[]
    # Every planned image gets a manifest record even when acquisition fails.
    for i,s in enumerate(selection):
        archive=archives[s['kind']]
        annotation_path=f"media/{s['type']}-{s['clip']}.json"
        try:
            raw=archive.member(s['annotation']); (root/annotation_path).write_bytes(raw)
            annotation_error=None
        except Exception as exc: annotation_error=type(exc).__name__+': '+str(exc)
        for e in s['images']:
            item_id=f"{s['type']}-{s['clip']}-{Path(e['name']).stem}"
            path='media/'+item_id+'.jpg'
            rec=dict(id=item_id,split=s['split'],type=s['type'],specimen=f"{s['type']}-{s['number']:02}",
                     identity_group=f"template-number-{s['number']:02}",capture=s['capture'],condition=s['condition'],
                     label={'or':'bona_fide_capture','cg':'print_copy','re':'screen_recapture'}[s['kind']],
                     path=path,annotation=annotation_path,frame_name=Path(e['name']).name,
                     source_member=e['name'],source_record=RECORDS[s['kind']],annotation_error=annotation_error)
            try:
                raw=archive.member(e); (root/path).write_bytes(raw)
                rec.update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),acquisition_error=None)
            except Exception as exc: rec.update(sha256=None,acquisition_error=type(exc).__name__+': '+str(exc))
            records.append(rec)
        if (i+1)%10==0: print(f"downloaded {i+1}/{len(selection)} clips; {net.bytes/1024**2:.1f} MiB",flush=True)
    write(root/'manifest.json',dict(records=records,network_bytes=net.bytes,requests=net.requests,
                                    policy_sha256=hashlib.sha256((root/'policy.json').read_bytes()).hexdigest(),
                                    members_sha256=hashlib.sha256((root/'members-frozen.json').read_bytes()).hexdigest(),
                                    license='CC-BY-SA-2.5; Generated Photos attribution',
                                    excluded_source_test=False))
    print('finished',net.bytes,flush=True)

if __name__=='__main__':
    raise SystemExit('Legacy importer disabled: unverified author split. Use fetch_train_only.py; historical source is quarantined privately.')
