#!/usr/bin/env python3
"""Snapshot only pinned source/model files; never enumerate TEST media."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
WORK = Path('/tmp/docscan-research-capture')
REV = 'dd96ed0d193cbc5e2a316bd9234524a08a44dbfc'
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

if __name__ == '__main__':
    os.umask(0o077)
    WORK.mkdir(exist_ok=False)
    source = WORK / 'source'
    source.mkdir()
    # Immutable git objects avoid other agents' in-flight working-tree edits.
    raw = subprocess.check_output(['git','archive',REV,'docscan','bench/lib','bench/suites','bench/manifests/barcode_public_dev.json','bench/manifests/barcode_synth_dev.json','experiments/public_id/score_id.py','experiments/public_id/midv500-dev-v1.json'],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(source,filter='data')
    models = WORK / 'models'
    models.mkdir()
    for name in ['text-detection.rten','text-recognition.rten']:
        shutil.copy2(ROOT/'models'/name,models/name)
    (WORK/'bin').mkdir()
    # Retain the current executable as well, but benchmark the source-built one.
    shutil.copy2(ROOT/'docscan/target/release/examples/scan', WORK/'bin/preexisting-scan')
    record = {'revision':REV,'source':{str(p.relative_to(source)):sha(p) for p in sorted(source.rglob('*')) if p.is_file()},'models':{p.name:sha(p) for p in models.iterdir()},'preexisting_binary':sha(WORK/'bin/preexisting-scan')}
    (WORK/'snapshot.json').write_text(json.dumps(record,indent=2)+'\n')
    print(WORK)
