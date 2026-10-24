#!/usr/bin/env python3
"""Publish only redacted aggregate evidence and immutable build/source receipts."""
import json
from pathlib import Path
import shutil

from prepare import HERE, WORK, ROOT, sha
from run import verify_receipt


def main():
    verify_receipt()
    assert sha(ROOT/'docscan/src/barcode.rs') == sha(WORK/'after/docscan/src/barcode.rs')
    files = ['accuracy.json','latency.json','frozen.json','source-receipt.json','tests-final.log']
    if (WORK/'analysis-revision.json').exists():
        files.append('analysis-revision.json')
    for name in files:
        assert (WORK/name).is_file(), name
    accuracy = json.loads((WORK/'accuracy.json').read_text())
    assert set(accuracy['datasets']) == {'barcode_public_dev','barcode_synth_dev'}
    for name, variants in accuracy['datasets'].items():
        for mode, trial in variants.items():
            assert len(trial['items']) == (277 if name=='barcode_public_dev' else 300)
            assert all(len(i['id'])==64 for i in trial['items'])
            assert all('barcodes' not in i and 'path' not in i for i in trial['items'])
            for metric in trial['metrics'].values():
                assert all(len(i)==64 and all(c in '0123456789abcdef' for c in i) for i in metric.get('ids',[]))
    dest = HERE/'evidence'
    dest.mkdir(exist_ok=False)
    for name in files:
        shutil.copy2(WORK/name,dest/name)
    (dest/'receipt.json').write_text(json.dumps({name:sha(dest/name) for name in files},indent=2)+'\n')
    print(dest)


if __name__=='__main__':
    main()
