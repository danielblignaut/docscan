#!/usr/bin/env python3
"""Fetch only the author's CC-BY London frontal photos; no access gates."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import urllib.request

REVISION = 'fa8b78fda2d659bb74ce62fcd99c4407551d2a77'
REPO = 'debruine/webmorphR.stim'
DEFAULT = Path('/tmp/docscan-public-data/face-london')


def fetch(root):
    os.umask(0o077)
    root = root.resolve()
    if not root.is_relative_to(Path('/tmp/docscan-public-data')):
        raise ValueError('Biometric data must stay under /tmp/docscan-public-data')
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    base = f'https://raw.githubusercontent.com/{REPO}/{REVISION}/'
    tree = json.load(urllib.request.urlopen(f'https://api.github.com/repos/{REPO}/git/trees/{REVISION}?recursive=1', timeout=60))['tree']
    files = [f for f in tree if f['path'].startswith(('inst/neutral_front/', 'inst/smiling_front/')) and f['path'].endswith('.jpg') and not Path(f['path']).name.startswith('.')]
    if len(files) != 204 or sum(f['size'] for f in files) > 120_000_000:
        raise ValueError('Unexpected pinned source tree')

    def one(f):
        dest = root / f['path']
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = dest.read_bytes() if dest.exists() else urllib.request.urlopen(base + f['path'], timeout=60).read(2_000_001)
        git_hash = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if len(data) != f['size'] or git_hash != f['sha']:
            raise ValueError('Source content does not match pinned git object')
        dest.write_bytes(data)
        return {'path': f['path'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'git_blob': git_hash}

    with ThreadPoolExecutor(max_workers=2) as pool:
        manifest = list(pool.map(one, files))
    # Preserve complete source notices locally; repository carries attribution, not photos.
    for name in ('README.md', 'LICENSE.md'):
        (root / ('source-' + name)).write_bytes(urllib.request.urlopen(base + name, timeout=60).read())
    result = {'source': f'https://github.com/{REPO}/tree/{REVISION}', 'revision': REVISION, 'doi': '10.6084/m9.figshare.5047666.v5', 'attribution': 'DeBruine, Lisa; Jones, Benedict (2017), Face Research Lab London Set', 'copyright_license': 'CC-BY-4.0', 'use': 'local research evaluation only; no shipped training; research participant consent does not establish commercial biometric consent', 'files': manifest}
    (root / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'downloaded_files': len(files), 'bytes': sum(f['bytes'] for f in manifest), 'manifest_sha256': hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT)
    fetch(parser.parse_args().root)
