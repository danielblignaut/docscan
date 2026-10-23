#!/usr/bin/env python3
"""Fetch a bounded public MIDV-500 DEV subset. Reserved layouts are never fetched."""
from __future__ import annotations
import argparse
import ftplib
import hashlib
import io
import json
import os
from pathlib import Path
import urllib.request
import zipfile

DEV = ('05_aze_passport', '16_deu_passport_new', '22_est_id')
RESERVED = ('32_lva_passport', '42_svk_id')
CONDITIONS = ('TA', 'CA', 'HA')
FRAMES = ('01', '15')
ROOT = Path('/tmp/docscan-public-data/midv500')
SOURCE = 'ftp://smartengines.com/midv-500/'

class RemoteZipFile(io.RawIOBase):
    """Read bounded FTP byte ranges without downloading surrounding archives."""
    def __init__(self, path):
        self.path, self.pos, self.bytes_read = path, 0, 0
        with self.connect() as ftp:
            self.size = ftp.size(path)
        if self.size is None:
            raise ValueError('FTP SIZE unavailable')

    @staticmethod
    def connect():
        ftp = ftplib.FTP('smartengines.com', timeout=30)
        ftp.login()
        ftp.voidcmd('TYPE I')
        return ftp

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else (self.pos if whence == 1 else self.size) + offset
        if not 0 <= self.pos <= self.size:
            raise ValueError('invalid seek')
        return self.pos

    def tell(self):
        return self.pos

    def read(self, size=-1):
        size = min(self.size-self.pos, size if size >= 0 else self.size)
        if size > 64*1024*1024:
            raise ValueError('remote range exceeds 64 MiB')
        if not size:
            return b''
        ftp = self.connect()
        try:
            with ftp.transfercmd('RETR '+self.path, rest=self.pos) as sock:
                data = bytearray()
                while len(data) < size:
                    chunk = sock.recv(min(1024*1024, size-len(data)))
                    if not chunk:
                        raise EOFError('truncated FTP range')
                    data.extend(chunk)
        finally:
            # RETR deliberately stops early; do not wait for the remaining ZIP.
            ftp.close()
        self.pos += size
        self.bytes_read += size
        return bytes(data)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root):
    import cv2
    import numpy as np
    from PIL import Image
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    files = []
    def write(rel, data):
        path = root/rel
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        os.chmod(path, 0o600)
        files.append({'path':rel, 'size':len(data), 'sha256':digest(path)})
    for name in ('license.txt','readme.txt','documents.pdf','md5.txt'):
        with urllib.request.urlopen(SOURCE+name, timeout=30) as response:
            write('provenance/'+name, response.read(2*1024*1024))
    records, downloaded = [], 0
    for layout in DEV:
        remote = RemoteZipFile('/midv-500/dataset/'+layout+'.zip')
        with zipfile.ZipFile(remote) as archive:
            prefix = layout+'/'
            truth_bytes = archive.read(prefix+'ground_truth/'+layout+'.json')
            write('raw/'+layout+'/truth.json', truth_bytes)
            truth = json.loads(truth_bytes)
            template_bytes = archive.read(prefix+'images/'+layout+'.tif')
            write('raw/'+layout+'/template.tif', template_bytes)
            width,height = Image.open(io.BytesIO(template_bytes)).size
            for condition in CONDITIONS:
                for frame in FRAMES:
                    stem = condition+layout[:2]+'_'+frame
                    member = prefix+'images/'+condition+'/'+stem+'.tif'
                    raw = archive.read(member)
                    annotation = archive.read(prefix+'ground_truth/'+condition+'/'+stem+'.json')
                    write('raw/'+layout+'/'+stem+'.tif', raw)
                    write('raw/'+layout+'/'+stem+'.json', annotation)
                    image = np.array(Image.open(io.BytesIO(raw)).convert('RGB'))
                    quad = np.float32(json.loads(annotation)['quad'])
                    target = np.float32([[0,0],[width,0],[width,height],[0,height]])
                    transform = cv2.getPerspectiveTransform(quad,target)
                    rectified = cv2.warpPerspective(image,transform,(width,height),borderMode=cv2.BORDER_CONSTANT,borderValue=(255,255,255))
                    for suffix,pixels in [('frame',image),('rectified',rectified)]:
                        buffer = io.BytesIO()
                        Image.fromarray(pixels).save(buffer,format='PNG')
                        write('dev/'+layout+'/'+stem+'_'+suffix+'.png',buffer.getvalue())
                    records.append({'id':layout+'/'+stem,'layout':layout,'split':'dev','condition':condition,
                        'frame':'dev/'+layout+'/'+stem+'_frame.png','rectified':'dev/'+layout+'/'+stem+'_rectified.png',
                        'fields':{key:value for key,value in truth.items() if 'value' in value},
                        'source_member':member,'all_corners_visible':bool(all(0 <= x < image.shape[1] and 0 <= y < image.shape[0] for x,y in quad))})
        downloaded += remote.bytes_read
        print(f'{layout}: {remote.bytes_read/1024**2:.1f} MiB fetched',flush=True)
    write('dev.json',(json.dumps(records,ensure_ascii=False,indent=2)+'\n').encode())
    manifest = {'schema':1,'source':SOURCE,'licence':'CC-BY-SA-2.5','dev_layouts':DEV,
        'reserved_layouts_not_fetched':RESERVED,'conditions':CONDITIONS,'frames':FRAMES,
        'downloaded_range_bytes':downloaded,'files':files}
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    os.chmod(root/'manifest.json',0o600)
    print(f'{len(records)} DEV frames; manifest={root/"manifest.json"}')


def verify(root):
    manifest = json.loads((root/'manifest.json').read_text())
    for entry in manifest['files']:
        path = root/entry['path']
        if digest(path) != entry['sha256'] or path.stat().st_size != entry['size']:
            raise ValueError(f'changed file: {entry["path"]}')
    print(f'verified {len(manifest["files"])} files')

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    if args.root.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        parser.error('dataset must remain outside the repository')
    os.umask(0o077)
    (verify if args.verify else prepare)(args.root)
