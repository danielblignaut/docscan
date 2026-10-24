#!/usr/bin/env python3
"""Verify frozen artifacts and export only text-free outcome/provenance records."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import zxingcpp
import run as base

HERE=Path(__file__).resolve().parent
DEST=HERE/'evidence'

def assert_redacted(value):
    if isinstance(value,dict):
        assert not ({'text','output','barcodes','bytes','lines','surname','given_names'} & set(value)), 'raw output keys in export'
        for child in value.values():assert_redacted(child)
    elif isinstance(value,list):
        for child in value:assert_redacted(child)

def export():
    DEST.mkdir(exist_ok=False)
    files={
        'id-round1.json':base.WORK/'id-results.json',
        'id-round2.json':base.WORK/'id-round2/results.json',
        'barcode-round1.json':base.WORK/'barcode-v2/barcode-results.json',
        'barcode-round2.json':base.WORK/'barcode-round2/results.json',
        'source-snapshot.json':base.WORK/'snapshot.json',
        'build-and-decoder-pin.json':base.WORK/'build-and-decoder-pin.json',
    }
    snapshot=json.loads((base.WORK/'snapshot.json').read_text())
    for relative,digest in snapshot['source'].items():assert base.sha(base.SOURCE/relative)==digest
    for name,digest in snapshot['models'].items():
        assert base.sha(base.WORK/'models'/name)==digest
        assert base.sha(base.WORK/'barcode-v2/models'/name)==digest
    build=json.loads(files['build-and-decoder-pin.json'].read_text())
    assert base.sha(base.WORK/'bin/scan')==build['baseline_binary']
    assert base.sha(base.WORK/'barcode-v2/bin/scan')==build['baseline_binary']
    for name,digest in build['zxingcpp_files'].items():assert base.sha(Path(zxingcpp.__file__).parent/name)==digest
    frozen=json.loads((base.WORK/'frozen-id.json').read_text())
    assert base.sha(HERE/'run.py')==frozen['runner_sha256']
    assert base.sha(HERE/'candidates.json')==frozen['config_sha256']
    assert base.sha(HERE/'zxing_worker.py')==frozen['zxing_worker_sha256']
    frozen2=json.loads((base.WORK/'barcode-v2/frozen-barcode.json').read_text())
    assert base.sha(HERE/'run_barcode_v2.py')==frozen2['runner_sha256']
    assert base.sha(HERE/'candidates-barcode-v2.json')==frozen2['config_sha256']
    assert base.sha(HERE/'zxing_worker_v2.py')==frozen2['zxing_worker_sha256']
    outcomes={}
    for name,source in files.items():
        value=json.loads(source.read_text())
        # 'fields' in ID evidence is a map of boolean correctness, never values.
        if name.startswith('id-'):
            for candidate in value['candidates'].values():
                assert len(candidate['items'])==18
                for item in candidate['items']:assert all(isinstance(v,bool) for v in item['fields'].values())
            # Validation is structural, allowing boolean MRZ field *names* below.
            filtered=json.loads(json.dumps(value))
            for candidate in filtered['candidates'].values():
                for item in candidate['items']:item.pop('fields')
            assert_redacted(filtered)
        else:assert_redacted(value)
        shutil.copy2(source,DEST/name)
        outcomes[name]=base.sha(source)
    for name in ['id','barcode']:
        source=base.WORK/f'frozen-{name}.json'
        shutil.copy2(source,DEST/f'initial-frozen-{name}.json')
    # Keep every completed trial from the aborted harness as redacted metadata.
    completed=[]
    for p in sorted((base.WORK/'private/barcode/barcode_public_dev').glob('*.json'),key=lambda p:int(p.stem)):
        raw=json.loads(p.read_text())
        completed.append({'id':'barcode_public_dev:'+p.stem,'input_sha256':raw['input_sha256'],
            'private_record_sha256':base.sha(p),'variants':{name:{'decode_count':len(out.get('barcodes',[])),
            'wall_ms':ms,**{key:bool(out.get(key)) for key in ['timeout','crash','error']}} for name,(out,ms) in raw['variants'].items()}})
    aborted={'valid_complete_benchmark':False,'reason':'OpenCV failed to load the pinned 100x1 WebP at public DEV index 141; original raw outputs and log retained privately',
        'completed_frames':len(completed),'planned_public_frames':277,'planned_synthetic_frames':300,
        'private_log_sha256':base.sha(base.WORK/'barcode.log'),'items':completed}
    base.write(DEST/'aborted-barcode-attempt.json',aborted)
    audit={'verified_utc':datetime.now(timezone.utc).isoformat(),'artifacts':outcomes,
        'native_source_and_binary_unchanged':True,'models_unchanged':True,'zxingcpp_package_bytes_unchanged':True,
        'test_or_reserved_access':False,'training_or_calibration':False,
        'initial_barcode_decoder_pin_note':'Extension-byte receipt was recorded after the aborted attempt and before the complete barcode-v2 run; initial attempt only froze package version.',
        'publishable_content':'Outcome booleans, counts, hashes, geometry metadata and provenance only; raw source text/media/payloads remain private.'}
    base.write(DEST/'audit.json',audit)
    print('exported',len(list(DEST.iterdir())),'redacted evidence files')

if __name__=='__main__':export()
