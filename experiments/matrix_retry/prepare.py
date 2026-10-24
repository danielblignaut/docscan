#!/usr/bin/env python3
"""Freeze source snapshots and a barcode-only native probe, never shared examples."""
from pathlib import Path
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'experiments/matrix_retry'
WORK = Path('/tmp/docscan-matrix-retry-v1')

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    os.umask(0o077)
    # Before was frozen at declaration, permit fresh reproduction too.
    protocol = json.loads((HERE/'protocol.json').read_text())
    if not WORK.exists():
        WORK.mkdir()
        (WORK/'before').mkdir()
        raw = subprocess.check_output(['git','archive',protocol['base_revision'],'docscan','bench/lib','bench/suites','bench/compare.py','bench/noise.json','bench/manifests/barcode_public_dev.json','bench/manifests/barcode_synth_dev.json'],cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            archive.extractall(WORK/'before',filter='data')
        shutil.copy2(HERE/'protocol.json',WORK/'protocol.json')
    assert sha(HERE/'protocol.json') == sha(WORK/'protocol.json')
    shutil.copytree(WORK/'before',WORK/'after')  # refuses overwrite
    shutil.copy2(ROOT/'docscan/src/barcode.rs',WORK/'after/docscan/src/barcode.rs')
    head = (HERE/'probe.rs').read_text()
    for side in ['before','after']:
        body = 'barcode::read_all(luma,w,h,None)' if side=='before' else '''match mode {
        "baseline" => barcode::read_all(luma,w,h,None),
        "matrix_both" => barcode::read_all_with_matrix_retries(luma,w,h,None),
        "empty_half" => barcode::read_all_with_empty_matrix_retry(luma,w,h,None),
        _ => panic!("unknown variant"),
    }'''
        function = 'fn scan(_mode: &str,luma: &[u8],w: u32,h: u32) -> Vec<barcode::Barcode> { let mode = _mode; '+body+' }'
        (WORK/side/'docscan/examples/matrix_probe.rs').write_text(head.replace('// PREPARE_SCAN_FUNCTION',function))
    (WORK/'source-receipt.json').write_text(json.dumps({str(p.relative_to(WORK)):sha(p) for side in ['before','after'] for p in sorted((WORK/side).rglob('*')) if p.is_file()},indent=2)+'\n')
    print(WORK)

if __name__ == '__main__':
    main()
