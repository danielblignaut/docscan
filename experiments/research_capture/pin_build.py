#!/usr/bin/env python3
"""Record the source-built baseline and decoder bytes before a fresh trial."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import zxingcpp
from prepare import WORK, sha

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    destination=WORK/'build-and-decoder-pin.json'
    if args.check:
        pinned=json.loads(destination.read_text())
        assert sha(WORK/'bin/scan')==pinned['baseline_binary']
        assert sha(WORK/'bin/preexisting-scan')==pinned['preserved_previous_binary']
        assert importlib.metadata.version('zxing-cpp')==pinned['zxingcpp_package_version']
        for name,digest in pinned['zxingcpp_files'].items():assert sha(Path(zxingcpp.__file__).parent/name)==digest
        print('preserved executables and decoder implementation match receipt')
        return
    if destination.exists():raise FileExistsError('Never replace a trial receipt; use --check')
    if not (WORK/'bin/scan').exists():shutil.copy2(WORK/'target/release/examples/scan',WORK/'bin/scan')
    record={'recorded_utc':datetime.now(timezone.utc).isoformat(),
        'build_command':'PATH=/home/dan/.cargo/bin:$PATH CARGO_TARGET_DIR=/tmp/docscan-research-capture/target /home/dan/.cargo/bin/cargo build --locked --release --example scan -j2 --manifest-path /tmp/docscan-research-capture/source/docscan/Cargo.toml',
        'compiler':subprocess.check_output(['/home/dan/.cargo/bin/rustc','-Vv'],text=True),
        'baseline_binary':sha(WORK/'bin/scan'),'preserved_previous_binary':sha(WORK/'bin/preexisting-scan'),
        'zxingcpp_package_version':importlib.metadata.version('zxing-cpp'),
        'zxingcpp_files':{p.name:sha(p) for p in sorted(Path(zxingcpp.__file__).parent.iterdir()) if p.is_file()},
        'model_sizes':{p.name:p.stat().st_size for p in (WORK/'models').iterdir()}}
    destination.write_text(json.dumps(record,indent=2)+'\n')
    print(destination)

if __name__=='__main__':main()
